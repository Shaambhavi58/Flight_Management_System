from fastapi import APIRouter, HTTPException, Depends
from services.service import AirportService
from controllers.auth_controller import get_current_user

router = APIRouter(prefix="/airports", tags=["Airports"])
airport_service = AirportService()

@router.get("")
def get_all_airports(user: dict = Depends(get_current_user)):
    """Retrieve all airports."""
    return airport_service.get_all_airports()

@router.get("/{airport_id}")
def get_airport(airport_id: int, user: dict = Depends(get_current_user)):
    """Retrieve a single airport by ID."""
    result = airport_service.get_airport_by_id(airport_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Airport not found")
    return result
