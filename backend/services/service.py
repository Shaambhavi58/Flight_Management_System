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
from typing import List, Optional
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

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_flight(self, flight_id: int, current_user: dict) -> bool:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can delete flights")
        with self._db.session_scope() as session:
            return self._repository.delete(session, flight_id)

    def clear_all_flights(self, airport_id: int = None) -> dict:
        with self._db.session_scope() as session:
            return self._repository.delete_all(session, airport_id=airport_id)


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