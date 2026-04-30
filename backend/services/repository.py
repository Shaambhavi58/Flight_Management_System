"""
services/repository.py
========================
Data Access Layer — all raw SQLAlchemy queries live here.
No business logic, no HTTP concerns, no role checks.

Duplicate prevention key for flights:
  (flight_number, departure_time, airport_id, flight_type)
  This 4-field composite uniquely identifies a flight slot.
"""

from sqlalchemy.orm import Session, joinedload   # joinedload eagerly fetches related objects
from sqlalchemy import UniqueConstraint
from models.models import FlightModel, AirlineModel, AirportModel, UserModel
from typing import List, Optional


class FlightRepository:
    """
    Handles all database operations for the flights table.
    Every method receives a SQLAlchemy Session from the caller — the repository
    never opens its own session, keeping transaction control in the service layer.
    """

    def __init__(self):
        pass  # stateless — all state lives in the injected session

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create(self, session: Session, flight_data: dict) -> FlightModel:
        """
        Insert a new flight row.
        - Strips internal metadata keys (prefixed with '_') and batch_id before insert
        - Resolves airline_code string → airline_id foreign key
        - Silently skips duplicates (same flight_number + dep_time + airport + type)
        Returns the new (or existing duplicate) FlightModel.
        """
        # Remove publisher metadata keys that should not be persisted to the DB
        clean_data = {
            k: v for k, v in flight_data.items()
            if not k.startswith("_") and k != "batch_id"  # strip _created_by_*, batch_id
        }

        # ── Resolve airline_code → airline_id ─────────────────────────────────
        if "airline_code" in clean_data:
            airline_code = clean_data.pop("airline_code")  # remove code from data dict

            # Look up the AirlineModel by IATA code (e.g. "6E", "AI")
            airline = session.query(AirlineModel).filter_by(code=airline_code).first()

            if airline:
                clean_data["airline_id"] = airline.id  # replace code with FK integer
            else:
                # Unknown airline code — skip this flight rather than inserting bad data
                print(f"[Repository] Unknown airline code: {airline_code}, skipping.")
                return None

        # ── Duplicate check (4-field composite key) ───────────────────────────
        existing = session.query(FlightModel).filter(
            FlightModel.flight_number  == clean_data.get("flight_number"),
            FlightModel.departure_time == clean_data.get("departure_time"),
            FlightModel.airport_id     == clean_data.get("airport_id"),
            FlightModel.flight_type    == clean_data.get("flight_type", "arrival"),
        ).first()

        if existing:
            # Log the skip for observability but do not raise an error
            print(f"[Repository] Duplicate skipped: {clean_data.get('flight_number')} "
                  f"@ airport_id={clean_data.get('airport_id')} "
                  f"dep={clean_data.get('departure_time')} "
                  f"type={clean_data.get('flight_type')}")
            return existing  # return the existing row so callers get a valid object

        # Build ORM instance from the cleaned data dict
        flight = FlightModel(**clean_data)
        session.add(flight)   # stage the INSERT (not committed yet)
        session.flush()       # flush to DB to get the auto-generated flight.id
        return flight

    # ── READ ALL ──────────────────────────────────────────────────────────────

    def get_all(self, session: Session, airport_id: int = None) -> List[FlightModel]:
        """
        Fetch all flights, optionally filtered by airport.
        joinedload pre-fetches airline and airport relationships in one query
        to avoid N+1 SELECT problems during serialization.
        """
        query = (
            session.query(FlightModel)
            .options(
                joinedload(FlightModel.airline),   # eagerly load airline.name, airline.code
                joinedload(FlightModel.airport)    # eagerly load airport.code, airport.city
            )
        )

        if airport_id:
            # Add WHERE clause to limit results to this airport
            query = query.filter(FlightModel.airport_id == airport_id)

        return query.all()  # execute and return full list

    # ── READ ONE ──────────────────────────────────────────────────────────────

    def get_by_id(self, session: Session, flight_id: int) -> Optional[FlightModel]:
        """
        Fetch a single flight by primary key.
        Returns None if no flight with that ID exists.
        Eager-loads relationships to avoid lazy-load errors after session closes.
        """
        return (
            session.query(FlightModel)
            .options(
                joinedload(FlightModel.airline),   # include airline details
                joinedload(FlightModel.airport)    # include airport details
            )
            .filter_by(id=flight_id)
            .first()  # returns None if not found
        )

    # ── UPDATE ────────────────────────────────────────────────────────────────

    def update(self, session: Session, flight_id: int, update_data: dict) -> Optional[FlightModel]:
        """
        Apply partial updates to an existing flight.
        Only fields present in update_data are modified (PATCH semantics).
        Resolves airline_code → airline_id if airline_code is in the update payload.
        Returns the refreshed FlightModel, or None if not found.
        """
        flight = session.query(FlightModel).filter_by(id=flight_id).first()

        if not flight:
            return None  # flight does not exist — caller raises 404

        # If the update includes a new airline_code, resolve it to an airline_id FK
        if "airline_code" in update_data:
            airline_code = update_data.pop("airline_code")  # extract and remove from dict
            airline = session.query(AirlineModel).filter_by(code=airline_code).first()
            if airline:
                flight.airline_id = airline.id  # update the FK

        # Dynamically apply remaining update fields using setattr
        for key, value in update_data.items():
            if hasattr(flight, key):          # only update fields that exist on the model
                setattr(flight, key, value)   # e.g. flight.status = "Delayed"

        session.flush()  # write changes to DB (within the current transaction)

        # Re-fetch with eager-loaded relationships to return a fully populated object
        return (
            session.query(FlightModel)
            .options(joinedload(FlightModel.airline), joinedload(FlightModel.airport))
            .filter_by(id=flight_id)
            .first()
        )

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete(self, session: Session, flight_id: int) -> bool:
        """
        Delete a single flight by primary key.
        Returns True if deleted, False if the flight was not found.
        """
        flight = session.query(FlightModel).filter_by(id=flight_id).first()

        if not flight:
            return False  # nothing to delete

        session.delete(flight)  # mark for DELETE
        session.flush()         # execute DELETE within current transaction
        return True

    # ── DELETE ALL ────────────────────────────────────────────────────────────

    def delete_all(self, session: Session, airport_id: int = None) -> int:
        """
        Bulk-delete flights. Optionally scoped to one airport.
        Returns the count of rows deleted.
        Used by flight_publisher before generating a fresh daily schedule.
        """
        query = session.query(FlightModel)  # start with all flights

        if airport_id:
            # Narrow delete to a specific airport only
            query = query.filter(FlightModel.airport_id == airport_id)

        count = query.delete()   # executes bulk DELETE and returns affected row count
        session.flush()          # commit the deletes within the current transaction
        return count

    # ── CLEAR TODAY'S FLIGHTS ─────────────────────────────────────────────────

    def clear_today_flights(self, session: Session, airport_id: int = None) -> int:
        """
        Delete all flights to prepare for a fresh daily schedule.
        Called at midnight by flight_publisher before publishing the new day's routes.
        Functionally identical to delete_all but with an explanatory log message.
        """
        query = session.query(FlightModel)

        if airport_id:
            query = query.filter(FlightModel.airport_id == airport_id)

        count = query.delete()   # bulk DELETE
        session.flush()
        print(f"[Repository] Cleared {count} flights before daily reset.")
        return count


class AirportRepository:
    """Read-only data access for the airports table."""

    def get_all(self, session: Session) -> List[AirportModel]:
        """Return all airports from the DB."""
        return session.query(AirportModel).all()

    def get_by_id(self, session: Session, airport_id: int) -> Optional[AirportModel]:
        """Return a single airport by primary key, or None if not found."""
        return session.query(AirportModel).filter_by(id=airport_id).first()

    def get_by_code(self, session: Session, code: str) -> Optional[AirportModel]:
        """Return an airport by IATA code (e.g. 'DEL', 'BOM'), or None."""
        return session.query(AirportModel).filter_by(code=code).first()


class UserRepository:
    """Data access methods for the users table."""

    def get_by_username(self, session: Session, username: str) -> Optional[UserModel]:
        """Look up a user by their unique username."""
        return session.query(UserModel).filter_by(username=username).first()

    def get_by_id(self, session: Session, user_id: int) -> Optional[UserModel]:
        """Look up a user by their DB primary key."""
        return session.query(UserModel).filter_by(id=user_id).first()

    def get_all(self, session: Session) -> List[UserModel]:
        """Return all registered users."""
        return session.query(UserModel).all()

    def create(self, session: Session, user_data: dict) -> UserModel:
        """
        Insert a new user row from a plain dict.
        The password_hash must already be hashed by the service layer before calling this.
        """
        user = UserModel(**user_data)  # unpack dict into ORM model constructor
        session.add(user)              # stage the INSERT
        session.flush()                # execute INSERT to get auto-generated user.id
        return user
