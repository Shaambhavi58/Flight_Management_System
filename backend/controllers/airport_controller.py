"""
controllers/airport_controller.py
===================================
FastAPI router for airport-related endpoints.
All endpoints require a valid JWT — no public access.
"""

from fastapi import APIRouter, HTTPException, Depends
from services.service import AirportService             # business logic for airport queries
from controllers.auth_controller import get_current_user  # JWT dependency injection

# All routes are prefixed with /airports and grouped under "Airports" in Swagger
router = APIRouter(prefix="/airports", tags=["Airports"])

# Single AirportService instance shared across all routes in this module
airport_service = AirportService()


@router.get("")
def get_all_airports(user: dict = Depends(get_current_user)):
    """
    Retrieve a list of all airports in the system.
    Any authenticated user (admin, staff, viewer) can access this endpoint.
    Used by the frontend to populate the airport selector cards on the dashboard.
    """
    # Delegate to service layer which queries the AirportRepository
    return airport_service.get_all_airports()


@router.get("/{airport_id}")
def get_airport(airport_id: int, user: dict = Depends(get_current_user)):
    """
    Retrieve a single airport by its database ID.
    Returns 404 if no airport with the given ID exists.
    """
    # Ask the service to look up the airport by primary key
    result = airport_service.get_airport_by_id(airport_id)

    # Raise 404 if the service returned None (airport does not exist)
    if result is None:
        raise HTTPException(status_code=404, detail="Airport not found")

    return result  # serialized dict: {id, name, code, city}
