"""
controllers/flight_controller.py
==================================
FastAPI router for flight CRUD operations with RBAC enforcement.

Access rules (enforced at BOTH controller and service layer for defence-in-depth):
  GET  /flights                    → all authenticated users (auto-scoped for staff/viewer)
  GET  /airports/{id}/flights      → all authenticated users (scoped for staff/viewer)
  GET  /flights/{id}               → all authenticated users (scoped for staff/viewer)
  POST /flights                    → admin and staff only (staff airport auto-assigned)
  PUT  /flights/{id}               → admin only
  DELETE /flights/{id}             → admin only
  DELETE /flights/clear-all        → admin only
"""

from fastapi import APIRouter, HTTPException, Depends
from services.service import FlightService                      # flight business logic
from models.schemas import FlightCreateSchema, FlightUpdateSchema, FlightSerializer  # validation & serialization
from controllers.auth_controller import get_current_user, require_admin, require_staff_or_admin  # RBAC deps
from utils.flight_create_publisher import publish_flight_create  # async RabbitMQ publish helper

# No prefix — flight routes are at root level (e.g. /flights, /airports/{id}/flights)
router = APIRouter(tags=["Flights"])

# Shared service instance for all route handlers in this module
flight_service = FlightService()


@router.get("/airports/{airport_id}/flights")
def get_airport_flights(
    airport_id: int,
    user: dict = Depends(get_current_user)  # any authenticated user may call this
):
    """
    Retrieve all flights for a specific airport.
    - Admin: sees all flights for the requested airport_id
    - Staff/Viewer: the airport_id parameter is ignored — service always returns
      flights for their own assigned airport (enforced in FlightService)
    """
    # Service handles RBAC scoping internally — pass the full user context
    return flight_service.get_all_flights(
        current_user=user,
        airport_id=airport_id  # may be overridden in service for staff/viewer
    )


@router.get("/flights")
def get_all_flights(
    time_of_day: str = None,   # optional filter: "morning", "afternoon", "evening"
    status: str = None,        # optional filter: "Scheduled", "Departed", etc.
    airport_id: int = None,    # optional filter: only used if user is admin
    user: dict = Depends(get_current_user)
):
    """
    Retrieve flights with optional filters.
    - Admin: can filter by any airport_id, time_of_day, or status
    - Staff/Viewer: airport_id is always overridden with their own airport from JWT
    """
    return flight_service.get_all_flights(
        current_user=user,
        airport_id=airport_id,      # admin-only; ignored for staff/viewer
        time_of_day=time_of_day,    # hour-based filter applied after DB query
        status=status,              # case-insensitive status match
    )


@router.get("/flights/{flight_id}")
def get_flight(flight_id: int, user: dict = Depends(get_current_user)):
    """
    Retrieve a single flight by its database ID.
    Staff and Viewer can only access flights belonging to their airport.
    Returns 404 if the flight does not exist or is not accessible.
    """
    # Service returns None for missing flights, raises 403 for wrong-airport access
    result = flight_service.get_flight_by_id(flight_id, current_user=user)

    if result is None:
        raise HTTPException(status_code=404, detail="Flight not found")

    return result


@router.post("/flights", status_code=202)
def create_flight(
    flight: FlightCreateSchema,
    user: dict = Depends(require_staff_or_admin),  # viewers get 403 automatically
):
    """
    Queue a new flight creation request via RabbitMQ.
    Returns 202 Accepted immediately — the flight is created asynchronously by worker.py.

    - Admin: must provide airport_id in request body
    - Staff: airport_id is silently overridden with their own assigned airport
    - Viewer: blocked by require_staff_or_admin dependency (HTTP 403)
    """
    role            = user["role"]         # "admin" or "staff" at this point
    user_airport_id = user.get("airport_id")  # the airport this staff member belongs to

    # Convert the Pydantic schema to a plain dict for publishing
    data = FlightSerializer.schema_to_dict(flight)

    if role == "staff":
        # Ignore whatever airport_id was in the request body —
        # staff must always create flights for their own airport only
        data["airport_id"] = user_airport_id

    elif role == "admin":
        # Admin must explicitly provide airport_id — no default exists
        if not data.get("airport_id"):
            raise HTTPException(
                status_code=400,
                detail="airport_id is required when creating a flight as admin"
            )

    # Attach audit metadata so the worker can log who triggered this creation
    data["_created_by_user_id"] = user.get("id")    # ID of the user making the request
    data["_created_by_role"]    = role               # role for audit trail

    try:
        # Publish the flight dict as a JSON message to the RabbitMQ queue
        publish_flight_create(data)
    except RuntimeError as e:
        # RabbitMQ is down — return a clear 503 so the client knows to retry
        raise HTTPException(
            status_code=503,
            detail=f"Flight queued failed — {e}. Start worker.py to process queued flights."
        )

    # Return 202 Accepted — the flight will appear in the board once worker.py processes it
    return {
        "message": "Flight creation queued successfully",
        "flight_number": data.get("flight_number"),  # echo back for client confirmation
        "airport_id": data.get("airport_id"),          # resolved airport (after staff override)
        "queued_by": user.get("username"),             # who triggered this request
        "note": "Flight will appear in the board once worker.py processes the queue."
    }


@router.put("/flights/{flight_id}")
def update_flight(
    flight_id: int,
    flight: FlightUpdateSchema,
    user: dict = Depends(require_admin),   # only admin can modify flight data
):
    """
    Update an existing flight's fields (admin only).
    All fields in FlightUpdateSchema are optional — only provided fields are changed.
    Returns 404 if flight does not exist.
    """
    # Convert update schema to dict, excluding fields not provided in the request
    data = FlightSerializer.update_schema_to_dict(flight)

    # Service performs the DB update and returns the refreshed flight
    result = flight_service.update_flight(flight_id, data, current_user=user)

    if result is None:
        raise HTTPException(status_code=404, detail="Flight not found")

    return result


@router.delete("/flights/clear-all")
def clear_all_flights(user: dict = Depends(require_admin)):
    """
    Delete ALL flights from the database (admin only).
    Used by flight_publisher before generating a fresh daily schedule.
    IMPORTANT: This route must be defined BEFORE /flights/{flight_id} to prevent
    FastAPI from matching "clear-all" as a flight_id integer.
    """
    count = flight_service.clear_all_flights()  # returns number of deleted rows
    return {"message": f"Cleared {count} flights"}


@router.delete("/flights/{flight_id}")
def delete_flight(
    flight_id: int,
    user: dict = Depends(require_admin),   # only admin can delete individual flights
):
    """
    Delete a single flight by its database ID (admin only).
    Returns 404 if the flight does not exist.
    """
    deleted = flight_service.delete_flight(flight_id, current_user=user)

    # Service returns False when no row matched the given flight_id
    if not deleted:
        raise HTTPException(status_code=404, detail="Flight not found")

    return {"message": f"Flight {flight_id} deleted successfully"}
