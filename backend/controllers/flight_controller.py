"""
controllers/flight_controller.py
==================================
FastAPI router for flight CRUD + carousel management with RBAC enforcement.

New endpoints:
  PUT  /flights/{id}/carousel        → admin and staff (change carousel assignment)
  GET  /flights/{id}/carousel-log    → all authenticated users (flight-specific log)
  GET  /flights/carousel-log         → all authenticated users (recent BHS events)
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from services.service import FlightService
from models.schemas import (
    FlightCreateSchema, FlightUpdateSchema, FlightResponseSchema, FlightSerializer,
    CarouselUpdateSchema,
)
from typing import List, Optional
from controllers.auth_controller import get_current_user, require_admin, require_staff_or_admin
from utils.flight_create_publisher import publish_flight_create

router = APIRouter(tags=["Flights"])
flight_service = FlightService()


# ── Gate Availability Endpoint ────────────────────────────────────────────────

@router.get("/gates/available")
def get_available_gates(
    airport_id: int,
    terminal: str,
    start_time: str,
    end_time: str,
    flight_id: Optional[int] = None,
    user: dict = Depends(get_current_user)
):
    """
    Returns all gates for the given airport and terminal that are:
    - Same airport
    - Same terminal
    - Status is NOT 'Maintenance'
    - Not assigned to another flight in the specified HH:MM time range.
    """
    return flight_service.get_available_gates(
        airport_id=airport_id,
        terminal=terminal,
        start_time=start_time,
        end_time=end_time,
        flight_id=flight_id
    )

from pydantic import BaseModel
class GateStatusUpdateSchema(BaseModel):
    status: str

@router.patch("/gates/{gate_id}/status")
def update_gate_status(
    gate_id: int,
    payload: GateStatusUpdateSchema,
    user: dict = Depends(require_staff_or_admin)
):
    """
    Update gate status (e.g., to 'Maintenance' or 'Available').
    Setting to Maintenance triggers operational alerts for the gate and assigned flights.
    """
    return flight_service.update_gate_status(gate_id, payload.status, current_user=user)


# ── Airport-scoped flights ────────────────────────────────────────────────────

@router.get("/airports/{airport_id}/flights", response_model=List[FlightResponseSchema])
def get_airport_flights(airport_id: int, user: dict = Depends(get_current_user)):
    return flight_service.get_all_flights(current_user=user, airport_id=airport_id)


# ── BHS Carousel Log (all recent events) ─────────────────────────────────────
# IMPORTANT: This route MUST be declared BEFORE /flights/{flight_id} to prevent
# FastAPI from interpreting "carousel-log" as a flight_id integer.

@router.get("/flights/carousel-log")
def get_carousel_log(
    limit: int = 20,
    user: dict = Depends(get_current_user),
):
    """
    Return the most recent carousel assignment/change events across all flights.
    Used by the frontend BHS log panel to show a live event feed.
    Accessible to all authenticated users.
    """
    return flight_service.get_carousel_log(limit=limit)


# ── All flights ───────────────────────────────────────────────────────────────

@router.get("/flights", response_model=List[FlightResponseSchema])
def get_all_flights(
    time_of_day: str = None,
    status: str = None,
    airport_id: int = None,
    user: dict = Depends(get_current_user)
):
    return flight_service.get_all_flights(
        current_user=user,
        airport_id=airport_id,
        time_of_day=time_of_day,
        status=status,
    )


# ── Single flight ─────────────────────────────────────────────────────────────

@router.get("/flights/{flight_id}", response_model=FlightResponseSchema)
def get_flight(flight_id: int, user: dict = Depends(get_current_user)):
    result = flight_service.get_flight_by_id(flight_id, current_user=user)
    if result is None:
        raise HTTPException(status_code=404, detail="Flight not found")
    return result


# ── Create flight ─────────────────────────────────────────────────────────────

@router.post("/flights", status_code=202)
def create_flight(flight: FlightCreateSchema, user: dict = Depends(require_staff_or_admin)):
    role            = user["role"]
    user_airport_id = user.get("airport_id")
    data            = FlightSerializer.schema_to_dict(flight)

    if role == "staff":
        data["airport_id"] = user_airport_id
    elif role == "admin":
        if not data.get("airport_id"):
            raise HTTPException(status_code=400, detail="airport_id is required when creating a flight as admin")

    data["_created_by_user_id"] = user.get("id")
    data["_created_by_role"]    = role

    try:
        publish_flight_create(data)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"Flight queued failed — {e}. Start worker.py to process queued flights.")

    return {
        "message":       "Flight creation queued successfully",
        "flight_number": data.get("flight_number"),
        "airport_id":    data.get("airport_id"),
        "queued_by":     user.get("username"),
        "note":          "Flight will appear in the board once worker.py processes the queue."
    }


# ── Update flight ─────────────────────────────────────────────────────────────

@router.put("/flights/{flight_id}")
def update_flight(
    flight_id: int,
    flight: FlightUpdateSchema,
    user: dict = Depends(require_admin),
):
    data   = FlightSerializer.update_schema_to_dict(flight)
    result = flight_service.update_flight(flight_id, data, current_user=user)
    if result is None:
        raise HTTPException(status_code=404, detail="Flight not found")
    return result


# ── Update carousel ───────────────────────────────────────────────────────────

@router.put("/flights/{flight_id}/carousel")
def update_carousel(
    flight_id: int,
    payload: CarouselUpdateSchema,
    user: dict = Depends(require_staff_or_admin),
):
    """
    Manually override the carousel assignment for an Arrived flight.

    Why staff can also do this (not just admin):
      In airport operations, ground staff are the ones who physically observe
      belt faults and need to reassign immediately — waiting for an admin
      to log in would cause baggage delays.

    The change is:
      1. Saved to DB (carousel_number on FlightModel)
      2. Logged in carousel_change_log (who, when, old→new, reason)
      3. Published to RabbitMQ bhs_queue as CAROUSEL_CHANGED event
         so Beumer's BHS can re-route the conveyor in real time.
    """
    return flight_service.update_carousel(
        flight_id=flight_id,
        new_carousel=payload.carousel_number,
        reason=payload.reason,
        current_user=user,
    )


# ── Carousel log for a specific flight ───────────────────────────────────────

@router.get("/flights/{flight_id}/carousel-log")
def get_flight_carousel_log(
    flight_id: int,
    user: dict = Depends(get_current_user),
):
    """Return the full carousel change history for a specific flight."""
    return flight_service.get_carousel_log_for_flight(flight_id)


# ── Status history for a specific flight ─────────────────────────────────────

@router.get("/flights/{flight_id}/history")
def get_flight_status_history(
    flight_id: int,
    user: dict = Depends(get_current_user),
):
    """Return the full status change history for a specific flight."""
    return flight_service.get_status_history_for_flight(flight_id)


# ── Clear gate change alert ───────────────────────────────────────────────────
# Must be declared BEFORE /flights/{flight_id} (dynamic int segment) to avoid
# FastAPI interpreting "clear-gate-alert" as an integer flight_id.

@router.patch("/flights/{flight_id}/clear-gate-alert")
def clear_gate_alert(
    flight_id: int,
    user: dict = Depends(get_current_user),
):
    """
    Acknowledge and clear the gate_changed flag for a flight.
    Accessible to all authenticated users — it's a non-destructive action.
    After clearing, the 'Gate Changed' badge disappears from the flight row.
    """
    return flight_service.clear_gate_alert(flight_id)


# ── Sync live ─────────────────────────────────────────────────────────────────

@router.post("/flights/sync-live")
def sync_live_flights(
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
):
    from flight_publisher import FlightDataOrchestrator
    orchestrator = FlightDataOrchestrator()
    triggered_by = user.get("username", "admin")
    background_tasks.add_task(orchestrator.run_once, triggered_by)
    return {
        "message":      "Generating today's full flight schedule for all 5 airports",
        "date":         str(__import__("datetime").datetime.now().date()),
        "note":         "Flights appear on board within seconds via RabbitMQ",
        "triggered_by": triggered_by,
    }


# ── Clear all flights ─────────────────────────────────────────────────────────

@router.delete("/flights/clear-all")
def clear_all_flights(user: dict = Depends(require_admin)):
    counts = flight_service.clear_all_flights()
    return {"message": f"Cleared {counts['flights']} flights and {counts['logs']} carousel logs"}


@router.delete("/flights/{flight_id}")
def delete_flight(flight_id: int, user: dict = Depends(require_admin)):
    deleted = flight_service.delete_flight(flight_id, current_user=user)
    if not deleted:
        raise HTTPException(status_code=404, detail="Flight not found")
    return {"message": f"Flight {flight_id} deleted successfully"}