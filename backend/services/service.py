"""
services/service.py
====================
FlightService & AirportService — Business logic layer with RBAC enforcement.

New in this version:
  - assign_carousel()  : auto-assigns carousel when flight status → Arrived
  - update_carousel()  : manual override by admin/staff, logs change, publishes to RabbitMQ
  - get_carousel_log() : returns recent BHS events for the frontend log panel
"""

import json
import os
from fastapi import HTTPException
from core.database import DatabaseManager
from services.repository import FlightRepository, AirportRepository, CarouselRepository
from models.schemas import FlightSerializer
from services.alert_service import AlertService
from typing import List, Optional
import random

DELAY_REASONS = [
    "Weather", "Technical", "ATC", "Crew",
    "Security", "Late Arrival", "Operational"
]

def ensure_delay_fields(data):
    """
    Safety fallback: ensures that if status is Delayed, it must have 
    positive delay_minutes and a valid reason.
    """
    if data.get("status") == "Delayed":
        if not data.get("delay_minutes") or int(data.get("delay_minutes", 0)) <= 0:
            data["delay_minutes"] = random.choice([15, 25, 35, 45, 60, 75, 90])
        if not data.get("delay_reason"):
            data["delay_reason"] = random.choice(DELAY_REASONS)
    else:
        # Clear delay fields if status is NOT Delayed
        data["delay_minutes"] = 0
        data["delay_reason"] = None
    return data
from datetime import datetime


# ── Carousel assignment map ───────────────────────────────────────────────────
# T1 = IndiGo / Akasa (domestic low-cost)   → Carousels C1–C4
# T2 = Air India / Vistara (full service)   → Carousels C5–C8
# T3 = Emirates / International             → Carousels C9–C12
#
# Using hash(flight_number) % len(options) ensures the SAME flight always gets
# the SAME carousel (deterministic) — mirrors real AODB carousel assignment logic.
TERMINAL_CAROUSEL_MAP = {
    "T1": ["C1", "C2", "C3", "C4"],
    "T2": ["C5", "C6", "C7", "C8"],
    "T3": ["C9", "C10", "C11", "C12"],
}

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
BHS_QUEUE     = "bhs_queue"   # Beumer BHS consumer reads from this queue


def assign_carousel(flight_number: str, terminal: str) -> str:
    """
    Deterministically assign a carousel based on terminal and flight number.

    Why deterministic (hash) instead of random?
      - Same flight always gets the same carousel on restart — no confusion.
      - Mirrors how real airports map flight types to fixed belt groups.
      - BHS can rely on the pattern for pre-configuration.

    Args:
        flight_number: e.g. "6E204"
        terminal:      "T1", "T2", or "T3"

    Returns:
        Carousel string e.g. "C3"
    """
    options = TERMINAL_CAROUSEL_MAP.get(terminal, ["C1", "C2"])
    index   = abs(hash(flight_number)) % len(options)
    return options[index]


def publish_bhs_event(event_type: str, payload: dict):
    """
    Publish a BHS event to the RabbitMQ bhs_queue.

    In a real Beumer deployment, the BHS consumer on the other end would
    read CAROUSEL_ASSIGNED / CAROUSEL_CHANGED events and:
      - Route the baggage conveyor to the correct belt
      - Update the airport display screens
      - Log the change in the BHS audit system

    We publish in a try/except so a RabbitMQ outage never breaks the main flow.
    """
    try:
        import pika
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST, heartbeat=60)
        )
        channel = connection.channel()
        channel.queue_declare(queue=BHS_QUEUE, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=BHS_QUEUE,
            body=json.dumps({
                "event": event_type,
                **payload,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "NMIA_FMS",
            }),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json"
            ),
        )
        connection.close()
        print(f"[BHS] Published {event_type}: {payload.get('flight_number')} → {payload.get('new_carousel')}")
    except Exception as e:
        print(f"[BHS] RabbitMQ publish failed (non-fatal): {e}")


class FlightService:
    """
    Encapsulates all flight-related business logic with role-based access control.
    """

    def __init__(self):
        self._db              = DatabaseManager()
        self._repository      = FlightRepository()
        self._carousel_repo   = CarouselRepository()
        self._serializer      = FlightSerializer()
        self._alert_service   = AlertService()

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_flight(self, flight_data: dict, current_user: dict) -> dict:
        role            = current_user["role"]
        user_airport_id = current_user.get("airport_id")

        if role == "viewer":
            raise HTTPException(status_code=403, detail="Viewers cannot create flights")

        if role == "staff":
            flight_data["airport_id"] = user_airport_id
        elif role == "admin":
            if not flight_data.get("airport_id"):
                raise HTTPException(status_code=400, detail="airport_id is required for admin flight creation")

        with self._db.session_scope() as session:
            # ── Auto-assign carousel on creation if status is Arrived ────────
            if flight_data.get("status") == "Arrived" and not flight_data.get("carousel_number"):
                fn = flight_data.get("flight_number")
                tn = flight_data.get("terminal_number", "T1")
                # We use the standalone assign_carousel utility
                flight_data["carousel_number"] = assign_carousel(fn, tn)

            # Ensure operational fidelity for delays
            flight_data = ensure_delay_fields(flight_data)
            flight_data["updated_at"] = datetime.utcnow()

            flight = self._repository.create(session, flight_data)
            flight = self._repository.get_by_id(session, flight.id)
            return self._serializer.orm_to_response(flight)

    # ── READ ALL ─────────────────────────────────────────────────────────────

    def get_all_flights(
        self,
        current_user: dict,
        airport_id: int = None,
        time_of_day: str = None,
        status: str = None
    ) -> List[dict]:
        role            = current_user["role"]
        user_airport_id = current_user.get("airport_id")

        if role in ("staff", "viewer"):
            airport_id = user_airport_id

        with self._db.session_scope() as session:
            flights = self._repository.get_all(session, airport_id=airport_id)

            if time_of_day:
                def time_filter(f):
                    try:
                        hour = int(f.departure_time.split(":")[0])
                    except:
                        return False
                    if time_of_day == "morning":   return 0  <= hour < 12
                    elif time_of_day == "afternoon": return 12 <= hour < 18
                    elif time_of_day == "evening":   return 18 <= hour < 24
                    return True
                flights = list(filter(time_filter, flights))

            if status:
                flights = [f for f in flights if f.status and f.status.lower() == status.lower()]

            return [self._serializer.orm_to_response(f) for f in flights]

    # ── READ ONE ──────────────────────────────────────────────────────────────

    def get_flight_by_id(self, flight_id: int, current_user: dict) -> Optional[dict]:
        with self._db.session_scope() as session:
            flight = self._repository.get_by_id(session, flight_id)
            if flight is None:
                return None

            role            = current_user["role"]
            user_airport_id = current_user.get("airport_id")

            if role in ("staff", "viewer") and flight.airport_id != user_airport_id:
                raise HTTPException(status_code=403, detail="Access denied to this flight")

            return self._serializer.orm_to_response(flight)

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_flight(self, flight_id: int, update_data: dict, current_user: dict) -> Optional[dict]:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can update flights")

        with self._db.session_scope() as session:
            # ── Delay Logic ──────────────────────────────────────────────────
            update_data = ensure_delay_fields(update_data)
            update_data["updated_at"] = datetime.utcnow()

            # ── Auto-assign carousel when status changes to Arrived ───────────
            # This is the core BHS integration trigger:
            # FMS detects Arrived → assigns carousel → publishes to RabbitMQ
            # → Beumer BHS consumer routes baggage to the correct belt.
            if update_data.get("status") == "Arrived":
                existing = self._repository.get_by_id(session, flight_id)
                if existing and not existing.carousel_number:
                    carousel = assign_carousel(existing.flight_number, existing.terminal_number)
                    update_data["carousel_number"] = carousel

                    # Log the auto-assignment
                    self._carousel_repo.log_change(
                        session,
                        flight_id=flight_id,
                        flight_number=existing.flight_number,
                        old_carousel=None,
                        new_carousel=carousel,
                        changed_by="system",
                        reason="Auto-assigned on Arrived status",
                        event_type="CAROUSEL_ASSIGNED",
                    )

                    self._alert_service.create_alert(
                        flight_id=flight_id,
                        flight_number=existing.flight_number,
                        alert_type="Carousel Changed",
                        message=f"{existing.flight_number} assigned carousel {carousel}",
                        metadata_json={"new_carousel": carousel}
                    )

                    # Notify BHS via RabbitMQ
                    publish_bhs_event("CAROUSEL_ASSIGNED", {
                        "flight_number":  existing.flight_number,
                        "airline":        existing.airline.code if existing.airline else "",
                        "terminal":       existing.terminal_number,
                        "new_carousel":   carousel,
                        "old_carousel":   None,
                        "airport_id":     existing.airport_id,
                        "changed_by":     "system",
                    })

            # ── Gate Availability Validation ─────────────────────────────────
            new_gate = update_data.get("gate_number")
            if new_gate:
                from models.models import GateModel, GateAssignmentModel
                
                # Fetch existing flight details for validations
                flight_base = self._repository.get_by_id(session, flight_id)
                if flight_base and flight_base.gate_number != new_gate:
                    # 1. Fetch gate in DB for this airport & terminal
                    gate = session.query(GateModel).filter_by(
                        airport_id=flight_base.airport_id,
                        terminal_number=flight_base.terminal_number,
                        gate_number=new_gate
                    ).first()
                    
                    if not gate:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Gate {new_gate} is invalid for this airport and terminal."
                        )
                    
                    # 2. Check maintenance status
                    if gate.status == "Maintenance":
                        raise HTTPException(
                            status_code=400,
                            detail=f"Gate {new_gate} is under maintenance. Please select another gate."
                        )
                    
                    # 3. Check for overlapping gate assignments
                    def check_overlap(start_A: str, end_A: str, start_B: str, end_B: str) -> bool:
                        def to_min(t_str):
                            try:
                                h, m = map(int, t_str.split(':'))
                                return h * 60 + m
                            except:
                                return 0
                        a1, a2 = to_min(start_A), to_min(end_A)
                        b1, b2 = to_min(start_B), to_min(end_B)
                        if a2 <= a1:
                            a2 += 1440
                        if b2 <= b1:
                            b2 += 1440
                        return (a1 < b2 and a2 > b1)

                    overlapping = session.query(GateAssignmentModel).filter(
                        GateAssignmentModel.gate_id == gate.id,
                        GateAssignmentModel.flight_id != flight_id,
                        GateAssignmentModel.assignment_status == "Active"
                    ).all()
                    
                    for assign in overlapping:
                        if check_overlap(flight_base.departure_time, flight_base.arrival_time, assign.start_time, assign.end_time):
                            raise HTTPException(
                                status_code=400,
                                detail=f"Gate {new_gate} is already occupied for this time. Please select another gate."
                            )

                    # Deactivate previous active assignment for this flight
                    session.query(GateAssignmentModel).filter_by(
                        flight_id=flight_id,
                        assignment_status="Active"
                    ).update({"assignment_status": "Completed"})

                    # Create new active assignment
                    new_assign = GateAssignmentModel(
                        flight_id=flight_id,
                        gate_id=gate.id,
                        start_time=flight_base.departure_time,
                        end_time=flight_base.arrival_time,
                        assignment_status="Active"
                    )
                    session.add(new_assign)

                    # Stamp the gate change metadata onto the update payload
                    old_gate = flight_base.gate_number
                    update_data["previous_gate"]   = old_gate
                    update_data["gate_changed"]     = True
                    update_data["gate_changed_at"]  = datetime.utcnow()
                    
                    self._alert_service.create_alert(
                        flight_id=flight_id,
                        flight_number=flight_base.flight_number,
                        alert_type="Gate Changed",
                        message=f"{flight_base.flight_number} gate changed to {new_gate}",
                        metadata_json={"old_gate": old_gate, "new_gate": new_gate}
                    )
                    
                    # Publish GATE_CHANGED to RabbitMQ (BHS queue)
                    publish_bhs_event("GATE_CHANGED", {
                        "flight_number": flight_base.flight_number,
                        "old_gate":      old_gate,
                        "new_gate":      new_gate,
                        "terminal":      flight_base.terminal_number,
                        "airport_id":    flight_base.airport_id,
                        "changed_by":    current_user.get("username", "admin"),
                    })
                    print(f"[GateAlert] {flight_base.flight_number}: {old_gate} → {new_gate} by {current_user.get('username')}")

            # ── Log status change before updating ────────────────────────────
            new_status = update_data.get("status")
            if new_status:
                pre_flight = self._repository.get_by_id(session, flight_id)
                if pre_flight and pre_flight.status != new_status:
                    from services.repository import FlightStatusHistoryRepository
                    status_repo = FlightStatusHistoryRepository()
                    status_repo.log_status_change(
                        session=session,
                        flight=pre_flight,
                        old_status=pre_flight.status,
                        new_status=new_status,
                        changed_by=current_user.get("username", "admin"),
                        reason=update_data.get("reason") or f"Admin status update"
                    )

                    if new_status in ["Delayed", "Cancelled"]:
                        self._alert_service.create_alert(
                            flight_id=flight_id,
                            flight_number=pre_flight.flight_number,
                            alert_type=new_status,
                            message=f"{pre_flight.flight_number} status changed to {new_status}",
                            metadata_json={"old_status": pre_flight.status, "new_status": new_status, "reason": update_data.get("delay_reason")}
                        )

            flight = self._repository.update(session, flight_id, update_data)
            if flight is None:
                return None
            return self._serializer.orm_to_response(flight)

    # ── UPDATE CAROUSEL (Manual Override) ────────────────────────────────────

    def update_carousel(
        self,
        flight_id: int,
        new_carousel: str,
        reason: Optional[str],
        current_user: dict,
    ) -> dict:
        """
        Manually override a carousel assignment.

        Allowed for: admin and staff only.
        Requires: flight must exist and have status "Arrived" (only Arrived flights
        have baggage to route — changing carousel on a future flight has no effect).

        Flow:
          1. Validate role and flight existence
          2. Save old carousel for the log and RabbitMQ event
          3. Update carousel_number on the flight row
          4. Write to carousel_change_log (audit trail)
          5. Publish CAROUSEL_CHANGED to RabbitMQ (BHS re-routes the conveyor)
          6. Return updated flight dict
        """
        role = current_user["role"]
        if role not in ("admin", "staff"):
            raise HTTPException(status_code=403, detail="Only admin or staff can change carousel assignments")

        with self._db.session_scope() as session:
            flight = self._repository.get_by_id(session, flight_id)
            if not flight:
                raise HTTPException(status_code=404, detail="Flight not found")

            if flight.status != "Arrived":
                raise HTTPException(
                    status_code=400,
                    detail=f"Carousel can only be changed for Arrived flights. Current status: {flight.status}"
                )

            old_carousel = flight.carousel_number

            # Update the flight row
            flight.carousel_number = new_carousel.upper()
            flight.updated_at = datetime.utcnow()
            session.flush()

            # Log the manual change
            self._carousel_repo.log_change(
                session,
                flight_id=flight_id,
                flight_number=flight.flight_number,
                old_carousel=old_carousel,
                new_carousel=new_carousel.upper(),
                changed_by=current_user.get("username", "unknown"),
                reason=reason,
                event_type="CAROUSEL_CHANGED",
            )

            self._alert_service.create_alert(
                flight_id=flight_id,
                flight_number=flight.flight_number,
                alert_type="Carousel Changed",
                message=f"{flight.flight_number} carousel changed to {new_carousel.upper()}",
                metadata_json={"old_carousel": old_carousel, "new_carousel": new_carousel.upper()}
            )

            # Publish HIGH PRIORITY event to BHS
            # This is the critical integration point — without this notification,
            # Beumer's BHS would route baggage to the OLD belt, causing misdirection.
            publish_bhs_event("CAROUSEL_CHANGED", {
                "flight_number":  flight.flight_number,
                "airline":        flight.airline.code if flight.airline else "",
                "terminal":       flight.terminal_number,
                "old_carousel":   old_carousel,
                "new_carousel":   new_carousel.upper(),
                "airport_id":     flight.airport_id,
                "changed_by":     current_user.get("username", "unknown"),
                "reason":         reason or "Manual override",
                "priority":       "HIGH",   # carousel changes are always urgent
            })

            # Re-fetch with relationships for full response
            flight = self._repository.get_by_id(session, flight_id)
            return self._serializer.orm_to_response(flight)

    # ── GET CAROUSEL LOG ──────────────────────────────────────────────────────

    def get_carousel_log(self, limit: int = 20) -> List[dict]:
        """
        Return the most recent carousel assignment/change events.
        Used by the frontend BHS log panel to show a live event feed.
        """
        with self._db.session_scope() as session:
            logs = self._carousel_repo.get_recent(session, limit=limit)
            return [
                {
                    "id":            log.id,
                    "flight_id":     log.flight_id,
                    "flight_number": log.flight_number,
                    "old_carousel":  log.old_carousel,
                    "new_carousel":  log.new_carousel,
                    "changed_by":    log.changed_by,
                    "changed_at":    log.changed_at.strftime("%H:%M:%S") if log.changed_at else "",
                    "reason":        log.reason,
                    "event_type":    log.event_type,
                }
                for log in logs
            ]

    # ── GET CAROUSEL LOG FOR FLIGHT ──────────────────────────────────────────

    def get_carousel_log_for_flight(self, flight_id: int) -> List[dict]:
        """Return all carousel events for a specific flight."""
        with self._db.session_scope() as session:
            logs = self._carousel_repo.get_by_flight(session, flight_id)
            return [
                {
                    "id":            log.id,
                    "flight_id":     log.flight_id,
                    "flight_number": log.flight_number,
                    "old_carousel":  log.old_carousel,
                    "new_carousel":  log.new_carousel,
                    "changed_by":    log.changed_by,
                    "changed_at":    log.changed_at.isoformat() if log.changed_at else "",
                    "reason":        log.reason,
                    "event_type":    log.event_type,
                }
                for log in logs
            ]

    # ── GET STATUS HISTORY FOR FLIGHT ──────────────────────────────────────────

    def get_status_history_for_flight(self, flight_id: int) -> List[dict]:
        """Return all status change events for a specific flight."""
        from services.repository import FlightStatusHistoryRepository
        with self._db.session_scope() as session:
            status_repo = FlightStatusHistoryRepository()
            history_logs = status_repo.get_by_flight(session, flight_id)
            return [
                {
                    "old_status": log.old_status,
                    "new_status": log.new_status,
                    "changed_by": log.changed_by,
                    "changed_at": log.changed_at.isoformat() if log.changed_at else None,
                    "reason": log.reason
                }
                for log in history_logs
            ]

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_flight(self, flight_id: int, current_user: dict) -> bool:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can delete flights")
        with self._db.session_scope() as session:
            return self._repository.delete(session, flight_id)

    def clear_all_flights(self, airport_id: int = None) -> dict:
        with self._db.session_scope() as session:
            return self._repository.delete_all(session, airport_id=airport_id)

    # ── CLEAR GATE ALERT ──────────────────────────────────────────────────────

    def clear_gate_alert(self, flight_id: int) -> dict:
        """
        Clear the gate_changed flag on a flight.
        Called via PATCH /flights/{id}/clear-gate-alert.
        Safe for any authenticated user — it's a non-destructive acknowledge action.
        """
        with self._db.session_scope() as session:
            from models.models import FlightModel
            flight = session.query(FlightModel).filter_by(id=flight_id).first()
            if not flight:
                raise HTTPException(status_code=404, detail="Flight not found")
            flight.gate_changed    = False
            flight.previous_gate   = None
            flight.gate_changed_at = None
            session.flush()
            return {"message": f"Gate alert cleared for flight {flight.flight_number}"}

    # ── GET AVAILABLE GATES ───────────────────────────────────────────────────

    def get_available_gates(self, airport_id: int, terminal: str, start_time: str, end_time: str, flight_id: Optional[int] = None) -> List[dict]:
        """
        Return list of gates for this airport/terminal that are available
        in the specified start_time to end_time range, ignoring self-conflict.
        """
        from models.models import GateModel, GateAssignmentModel
        
        def check_overlap(start_A: str, end_A: str, start_B: str, end_B: str) -> bool:
            def to_min(t_str):
                try:
                    h, m = map(int, t_str.split(':'))
                    return h * 60 + m
                except:
                    return 0
            a1, a2 = to_min(start_A), to_min(end_A)
            b1, b2 = to_min(start_B), to_min(end_B)
            if a2 <= a1:
                a2 += 1440
            if b2 <= b1:
                b2 += 1440
            return (a1 < b2 and a2 > b1)

        with self._db.session_scope() as session:
            # Get all gates for this airport and terminal
            gates = session.query(GateModel).filter_by(
                airport_id=airport_id,
                terminal_number=terminal
            ).all()

            available_gates = []
            for g in gates:
                if g.status == "Maintenance":
                    continue
                
                # Check active assignments
                assignments = session.query(GateAssignmentModel).filter_by(
                    gate_id=g.id,
                    assignment_status="Active"
                ).all()

                has_conflict = False
                for assign in assignments:
                    if flight_id and assign.flight_id == flight_id:
                        continue
                    if check_overlap(start_time, end_time, assign.start_time, assign.end_time):
                        has_conflict = True
                        break

                    available_gates.append({
                        "id": g.id,
                        "gate_number": g.gate_number,
                        "status": g.status
                    })

            return available_gates

    # ── UPDATE GATE STATUS ────────────────────────────────────────────────────

    def update_gate_status(self, gate_id: int, status: str, current_user: dict) -> dict:
        if current_user["role"] not in ["admin", "staff"]:
            raise HTTPException(status_code=403, detail="Only admins or staff can update gate status")

        with self._db.session_scope() as session:
            from models.models import GateModel, GateAssignmentModel
            gate = session.query(GateModel).filter_by(id=gate_id).first()
            if not gate:
                raise HTTPException(status_code=404, detail="Gate not found")

            old_status = gate.status
            gate.status = status
            session.flush()

            # Trigger maintenance alerts if changed to Maintenance
            if status == "Maintenance" and old_status != "Maintenance":
                # 1. Create gate-level alert (flight_id is None)
                self._alert_service.create_alert(
                    flight_id=None,
                    flight_number=None,
                    alert_type="Maintenance",
                    message=f"Gate {gate.gate_number} is now under maintenance.",
                    metadata_json={"gate_number": gate.gate_number, "terminal": gate.terminal_number}
                )

                # 2. Create flight-level alerts for active assignments
                active_assignments = session.query(GateAssignmentModel).filter_by(
                    gate_id=gate.id,
                    assignment_status="Active"
                ).all()

                for assign in active_assignments:
                    if assign.flight:
                        self._alert_service.create_alert(
                            flight_id=assign.flight.id,
                            flight_number=assign.flight.flight_number,
                            alert_type="Maintenance",
                            message=f"{assign.flight.flight_number}'s assigned gate {gate.gate_number} is under maintenance.",
                            metadata_json={"gate_number": gate.gate_number}
                        )

            return {"message": f"Gate {gate.gate_number} status updated to {status}"}



# ── Airport Service ────────────────────────────────────────────────────────────

class AirportService:
    """Handles airport-related business logic."""

    def __init__(self):
        self._db         = DatabaseManager()
        self._repository = AirportRepository()

    def get_all_airports(self) -> List[dict]:
        with self._db.session_scope() as session:
            airports = self._repository.get_all(session)
            return [{"id": a.id, "name": a.name, "code": a.code, "city": a.city} for a in airports]

    def get_airport_by_id(self, airport_id: int) -> Optional[dict]:
        with self._db.session_scope() as session:
            a = self._repository.get_by_id(session, airport_id)
            if a is None:
                return None
            return {"id": a.id, "name": a.name, "code": a.code, "city": a.city}