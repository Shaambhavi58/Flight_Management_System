"""
Flight Controller — FastAPI router with RBAC enforcement.

Access rules (enforced at both controller and service layer):
  - GET /flights           → all authenticated users (auto-filtered by airport for staff/viewer)
  - GET /airports/{id}/flights → all authenticated users (scoped for staff/viewer)
  - GET /flights/{id}      → all authenticated users (scoped for staff/viewer)
  - POST /flights          → admin and staff only (staff auto-assigned their airport)
  - PUT /flights/{id}      → admin only
  - DELETE /flights/{id}   → admin only
"""

from fastapi import APIRouter, HTTPException, Depends
from services.service import FlightService
from models.schemas import FlightCreateSchema, FlightUpdateSchema, FlightSerializer
from controllers.auth_controller import get_current_user, require_admin, require_staff_or_admin
from utils.flight_create_publisher import publish_flight_create

router = APIRouter(tags=["Flights"])
flight_service = FlightService()


@router.get("/airports/{airport_id}/flights")
def get_airport_flights(
    airport_id: int,
    user: dict = Depends(get_current_user)
):
    """
    Retrieve all flights for a specific airport.
    - Admin: sees all flights for the given airport
    - Staff/Viewer: only sees flights for THEIR airport (airport_id param ignored if mismatched)
    """
    return flight_service.get_all_flights(
        current_user=user,
        airport_id=airport_id
    )


@router.get("/flights")
def get_all_flights(
    time_of_day: str = None,
    status: str = None,
    airport_id: int = None,
    user: dict = Depends(get_current_user)
):
    """
    Retrieve flights.
    - Admin: all flights (optionally filtered by airport_id)
    - Staff/Viewer: scoped to their assigned airport automatically
    """
    return flight_service.get_all_flights(
        current_user=user,
        airport_id=airport_id,
        time_of_day=time_of_day,
        status=status,
    )


@router.get("/flights/{flight_id}")
def get_flight(flight_id: int, user: dict = Depends(get_current_user)):
    """Retrieve a single flight by ID (scoped for staff/viewer)."""
    result = flight_service.get_flight_by_id(flight_id, current_user=user)
    if result is None:
        raise HTTPException(status_code=404, detail="Flight not found")
    return result


@router.post("/flights", status_code=202)
def create_flight(
    flight: FlightCreateSchema,
    user: dict = Depends(require_staff_or_admin),
):
    """
    Queue a new flight creation request via RabbitMQ.

    - Admin: must provide airport_id in body
    - Staff: airport_id is auto-assigned from their profile (body value ignored)
    - Viewer: 403 Forbidden

    Returns 202 Accepted — the flight will be inserted asynchronously by worker.py.
    Start the worker with: python worker.py
    """
    role           = user["role"]
    user_airport_id = user.get("airport_id")

    # Resolve airport_id before publishing
    data = FlightSerializer.schema_to_dict(flight)

    if role == "staff":
        # Always override with the staff member's assigned airport
        data["airport_id"] = user_airport_id
    elif role == "admin":
        if not data.get("airport_id"):
            raise HTTPException(
                status_code=400,
                detail="airport_id is required when creating a flight as admin"
            )

    # Add metadata so worker can log who initiated the request
    data["_created_by_user_id"] = user.get("id")
    data["_created_by_role"]    = role

    try:
        publish_flight_create(data)
    except RuntimeError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Flight queued failed — {e}. Start worker.py to process queued flights."
        )

    return {
        "message": "Flight creation queued successfully",
        "flight_number": data.get("flight_number"),
        "airport_id": data.get("airport_id"),
        "queued_by": user.get("username"),
        "note": "Flight will appear in the board once worker.py processes the queue."
    }


@router.put("/flights/{flight_id}")
def update_flight(
    flight_id: int,
    flight: FlightUpdateSchema,
    user: dict = Depends(require_admin),  # Only admin can update
):
    """Update an existing flight (admin only)."""
    data = FlightSerializer.update_schema_to_dict(flight)
    result = flight_service.update_flight(flight_id, data, current_user=user)
    if result is None:
        raise HTTPException(status_code=404, detail="Flight not found")
    return result


@router.delete("/flights/clear-all")
def clear_all_flights(user: dict = Depends(require_admin)):
    """Clear ALL flights from the database (admin only). Must be defined before /flights/{flight_id}."""
    count = flight_service.clear_all_flights()
    return {"message": f"Cleared {count} flights"}


@router.delete("/flights/{flight_id}")
def delete_flight(
    flight_id: int,
    user: dict = Depends(require_admin),  # Only admin can delete
):
    """Delete a flight by ID (admin only)."""
    deleted = flight_service.delete_flight(flight_id, current_user=user)
    if not deleted:
        raise HTTPException(status_code=404, detail="Flight not found")
    return {"message": f"Flight {flight_id} deleted successfully"}
