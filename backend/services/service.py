"""
services/service.py
====================
FlightService & AirportService — Business logic layer with RBAC enforcement.

This layer sits between controllers (HTTP) and the repository (DB queries).
It owns all business rules: role checking, airport scoping, time filtering.
Controllers should never write SQL. Repositories should never check roles.
"""

from fastapi import HTTPException
from core.database import DatabaseManager               # singleton DB engine
from services.repository import FlightRepository, AirportRepository  # DB query layer
from models.schemas import FlightSerializer             # ORM → dict conversion
from typing import List, Optional


class FlightService:
    """
    Encapsulates all flight-related business logic with role-based access control.

    Role behaviour:
      Admin  → full access to all airports
      Staff  → read/create for their assigned airport only
      Viewer → read-only for their assigned airport only
    """

    def __init__(self):
        self._db         = DatabaseManager()    # shared singleton — one DB connection pool
        self._repository = FlightRepository()  # data access object
        self._serializer = FlightSerializer()  # converts ORM rows to response dicts

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create_flight(self, flight_data: dict, current_user: dict) -> dict:
        """
        Persist a new flight to the database.
        RBAC rules:
          - Viewer: blocked with HTTP 403
          - Staff: airport_id is always overridden with their assigned airport
          - Admin: must provide airport_id explicitly
        """
        role            = current_user["role"]         # extract role from JWT payload
        user_airport_id = current_user.get("airport_id")  # None for admin

        # Viewers have no write access to flights
        if role == "viewer":
            raise HTTPException(status_code=403, detail="Viewers cannot create flights")

        if role == "staff":
            # Override any airport_id the client sent — staff are airport-scoped
            flight_data["airport_id"] = user_airport_id

        elif role == "admin":
            # Admin must explicitly state which airport the flight belongs to
            if not flight_data.get("airport_id"):
                raise HTTPException(
                    status_code=400,
                    detail="airport_id is required for admin flight creation"
                )

        with self._db.session_scope() as session:
            # Create the DB row via repository (handles duplicate check internally)
            flight = self._repository.create(session, flight_data)

            # Re-fetch with eager-loaded relationships (airline, airport) for full response
            flight = self._repository.get_by_id(session, flight.id)

            # Serialize to dict before session closes (ORM objects expire after commit)
            return self._serializer.orm_to_response(flight)

    # ── READ ALL ─────────────────────────────────────────────────────────────

    def get_all_flights(
        self,
        current_user: dict,
        airport_id: int = None,
        time_of_day: str = None,
        status: str = None
    ) -> List[dict]:
        """
        Retrieve flights with RBAC airport scoping and optional filters.

        Filters applied in order:
          1. Airport scope (mandatory for staff/viewer)
          2. Time of day (optional)
          3. Status (optional)
        """
        role            = current_user["role"]
        user_airport_id = current_user.get("airport_id")

        # Staff and viewer always see only their airport — override any client value
        if role in ("staff", "viewer"):
            airport_id = user_airport_id   # ignore airport_id from query params

        with self._db.session_scope() as session:
            # Fetch flights from DB, filtered by airport if specified
            flights = self._repository.get_all(session, airport_id=airport_id)

            # ── Time-of-day filter ─────────────────────────────────────────
            if time_of_day:
                def time_filter(f):
                    """Inner function: parse departure hour and check range."""
                    try:
                        hour = int(f.departure_time.split(":")[0])  # extract HH from "HH:MM"
                    except:
                        return False  # skip flights with unparseable departure times

                    # Map time_of_day string to hour ranges
                    if time_of_day == "morning":
                        return 0 <= hour < 12    # midnight to noon
                    elif time_of_day == "afternoon":
                        return 12 <= hour < 18   # noon to 6 PM
                    elif time_of_day == "evening":
                        return 18 <= hour < 24   # 6 PM to midnight

                    return True  # unknown time_of_day value — include all

                # Apply the filter, converting the query result to a plain list
                flights = list(filter(time_filter, flights))

            # ── Status filter ──────────────────────────────────────────────
            if status:
                # Case-insensitive comparison so "scheduled" == "Scheduled"
                flights = [
                    f for f in flights
                    if f.status and f.status.lower() == status.lower()
                ]

            # Serialize all remaining ORM objects to dicts before session closes
            return [self._serializer.orm_to_response(f) for f in flights]

    # ── READ ONE ──────────────────────────────────────────────────────────────

    def get_flight_by_id(self, flight_id: int, current_user: dict) -> Optional[dict]:
        """
        Retrieve a single flight by ID with RBAC airport scoping.
        Staff/Viewer can only access flights belonging to their airport.
        Returns None if the flight doesn't exist; raises 403 for wrong-airport access.
        """
        with self._db.session_scope() as session:
            flight = self._repository.get_by_id(session, flight_id)

            if flight is None:
                return None  # 404 raised by the controller

            role            = current_user["role"]
            user_airport_id = current_user.get("airport_id")

            # Enforce airport scoping for non-admin users
            if role in ("staff", "viewer") and flight.airport_id != user_airport_id:
                raise HTTPException(status_code=403, detail="Access denied to this flight")

            return self._serializer.orm_to_response(flight)

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update_flight(self, flight_id: int, update_data: dict, current_user: dict) -> Optional[dict]:
        """
        Update a flight's fields. Admin only.
        Only fields present in update_data are modified (partial update).
        """
        # Double-check role at service level even though controller also checks
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can update flights")

        with self._db.session_scope() as session:
            flight = self._repository.update(session, flight_id, update_data)

            if flight is None:
                return None  # flight not found — controller raises 404

            return self._serializer.orm_to_response(flight)

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete_flight(self, flight_id: int, current_user: dict) -> bool:
        """
        Delete a flight by ID. Admin only.
        Returns True if deleted, False if the flight did not exist.
        """
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can delete flights")

        with self._db.session_scope() as session:
            return self._repository.delete(session, flight_id)  # True / False

    # ── CLEAR ALL ─────────────────────────────────────────────────────────────

    def clear_all_flights(self, airport_id: int = None) -> int:
        """
        Delete all flights from the DB (admin utility).
        Optionally scoped to a single airport. Returns the count of deleted rows.
        """
        with self._db.session_scope() as session:
            return self._repository.delete_all(session, airport_id=airport_id)


# ── Airport Service ────────────────────────────────────────────────────────────

class AirportService:
    """
    Handles airport-related business logic.
    Currently read-only — airports are seeded at startup via app.py.
    """

    def __init__(self):
        self._db         = DatabaseManager()    # shared singleton DB manager
        self._repository = AirportRepository()  # airport DB query layer

    def get_all_airports(self) -> List[dict]:
        """Return all airports as a list of plain dicts."""
        with self._db.session_scope() as session:
            airports = self._repository.get_all(session)  # list of AirportModel ORM objects

            # Manually project to dicts — no dedicated serializer needed for airports
            return [
                {
                    "id":   a.id,
                    "name": a.name,
                    "code": a.code,
                    "city": a.city
                }
                for a in airports
            ]

    def get_airport_by_id(self, airport_id: int) -> Optional[dict]:
        """Return a single airport by primary key, or None if not found."""
        with self._db.session_scope() as session:
            a = self._repository.get_by_id(session, airport_id)

            if a is None:
                return None  # controller will raise 404

            return {
                "id":   a.id,
                "name": a.name,
                "code": a.code,
                "city": a.city
            }