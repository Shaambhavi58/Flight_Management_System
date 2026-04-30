"""
FlightService & AirportService — Business logic layer with RBAC enforcement.
"""

from fastapi import HTTPException
from core.database import DatabaseManager
from services.repository import FlightRepository, AirportRepository
from models.schemas import FlightSerializer
from typing import List, Optional


class FlightService:
    """
    Service class encapsulating flight business logic with role-based access control.
    - Admin: full access to all airports
    - Staff: can read/create flights for their airport only
    - Viewer: read-only access to their airport's flights
    """

    def __init__(self):
        self._db = DatabaseManager()
        self._repository = FlightRepository()
        self._serializer = FlightSerializer()

    # ── CREATE ──────────────────────────────────────
    def create_flight(self, flight_data: dict, current_user: dict) -> dict:
        """
        Create a new flight.
        - Admin: can specify any airport_id
        - Staff: airport_id is automatically set from the user's assigned airport
        - Viewer: cannot create flights (403)
        """
        role = current_user["role"]
        user_airport_id = current_user.get("airport_id")

        if role == "viewer":
            raise HTTPException(status_code=403, detail="Viewers cannot create flights")

        if role == "staff":
            # Ignore whatever airport_id was sent — always use the staff's airport
            flight_data["airport_id"] = user_airport_id
        elif role == "admin":
            # Admin must provide airport_id
            if not flight_data.get("airport_id"):
                raise HTTPException(status_code=400, detail="airport_id is required for admin flight creation")

        with self._db.session_scope() as session:
            flight = self._repository.create(session, flight_data)
            flight = self._repository.get_by_id(session, flight.id)
            return self._serializer.orm_to_response(flight)

    # ── READ ALL ────────────────────────────────────
    def get_all_flights(
        self,
        current_user: dict,
        airport_id: int = None,
        time_of_day: str = None,
        status: str = None
    ) -> List[dict]:
        """
        Retrieve flights with RBAC filtering:
        - Admin: can see all flights (optional airport_id filter)
        - Staff/Viewer: always scoped to their airport_id
        """
        role = current_user["role"]
        user_airport_id = current_user.get("airport_id")

        # Enforce airport scoping for staff/viewer
        if role in ("staff", "viewer"):
            airport_id = user_airport_id  # override any passed value

        with self._db.session_scope() as session:
            flights = self._repository.get_all(session, airport_id=airport_id)

            # 🔹 TIME FILTER
            if time_of_day:
                def time_filter(f):
                    try:
                        hour = int(f.departure_time.split(":")[0])
                    except:
                        return False

                    if time_of_day == "morning":
                        return 0 <= hour < 12
                    elif time_of_day == "afternoon":
                        return 12 <= hour < 18
                    elif time_of_day == "evening":
                        return 18 <= hour < 24

                    return True

                flights = list(filter(time_filter, flights))

            # 🔥 STATUS FILTER
            if status:
                flights = [
                    f for f in flights
                    if f.status and f.status.lower() == status.lower()
                ]

            # ✅ RETURN SERIALIZED DATA
            return [self._serializer.orm_to_response(f) for f in flights]

    # ── READ ONE ────────────────────────────────────
    def get_flight_by_id(self, flight_id: int, current_user: dict) -> Optional[dict]:
        """
        Retrieve a single flight by ID.
        Staff/Viewer are restricted to their airport's flights.
        """
        with self._db.session_scope() as session:
            flight = self._repository.get_by_id(session, flight_id)
            if flight is None:
                return None

            # Scope check for staff/viewer
            role = current_user["role"]
            user_airport_id = current_user.get("airport_id")
            if role in ("staff", "viewer") and flight.airport_id != user_airport_id:
                raise HTTPException(status_code=403, detail="Access denied to this flight")

            return self._serializer.orm_to_response(flight)

    # ── UPDATE ──────────────────────────────────────
    def update_flight(self, flight_id: int, update_data: dict, current_user: dict) -> Optional[dict]:
        """
        Update a flight. Admin only.
        """
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can update flights")

        with self._db.session_scope() as session:
            flight = self._repository.update(session, flight_id, update_data)
            if flight is None:
                return None
            return self._serializer.orm_to_response(flight)

    # ── DELETE ──────────────────────────────────────
    def delete_flight(self, flight_id: int, current_user: dict) -> bool:
        """
        Delete a flight. Admin only.
        """
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can delete flights")

        with self._db.session_scope() as session:
            return self._repository.delete(session, flight_id)

    # ── CLEAR ALL ───────────────────────────────────
    def clear_all_flights(self, airport_id: int = None) -> int:
        """Delete all flights (admin utility)."""
        with self._db.session_scope() as session:
            return self._repository.delete_all(session, airport_id=airport_id)


# ──────────────────────────────────────────────
# AIRPORT SERVICE
# ──────────────────────────────────────────────

class AirportService:
    """
    Service class for airport-related business logic.
    """

    def __init__(self):
        self._db = DatabaseManager()
        self._repository = AirportRepository()

    def get_all_airports(self) -> List[dict]:
        """Retrieve all airports."""
        with self._db.session_scope() as session:
            airports = self._repository.get_all(session)
            return [
                {
                    "id": a.id,
                    "name": a.name,
                    "code": a.code,
                    "city": a.city
                }
                for a in airports
            ]

    def get_airport_by_id(self, airport_id: int) -> Optional[dict]:
        """Retrieve a single airport."""
        with self._db.session_scope() as session:
            a = self._repository.get_by_id(session, airport_id)
            if a is None:
                return None
            return {
                "id": a.id,
                "name": a.name,
                "code": a.code,
                "city": a.city
            }