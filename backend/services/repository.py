"""
repository.py — CRUD operations with proper duplicate prevention.

Duplicate check uses: flight_number + departure_time + airport_id + flight_type
This combination uniquely identifies a flight slot.
"""

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import UniqueConstraint
from models.models import FlightModel, AirlineModel, AirportModel, UserModel
from typing import List, Optional


class FlightRepository:

    def __init__(self):
        pass

    # ── CREATE ──────────────────────────────────────
    def create(self, session: Session, flight_data: dict) -> FlightModel:
        """
        Create a flight. Skips duplicates silently.
        Duplicate = same flight_number + departure_time + airport_id + flight_type
        """
        clean_data = {k: v for k, v in flight_data.items() if not k.startswith("_") and k != "batch_id"}

        # Resolve airline_code → airline_id
        if "airline_code" in clean_data:
            airline_code = clean_data.pop("airline_code")
            airline = session.query(AirlineModel).filter_by(code=airline_code).first()
            if airline:
                clean_data["airline_id"] = airline.id
            else:
                print(f"[Repository] Unknown airline code: {airline_code}, skipping.")
                return None

        # ── Duplicate check (4-field key) ──────────────
        existing = session.query(FlightModel).filter(
            FlightModel.flight_number  == clean_data.get("flight_number"),
            FlightModel.departure_time == clean_data.get("departure_time"),
            FlightModel.airport_id     == clean_data.get("airport_id"),
            FlightModel.flight_type    == clean_data.get("flight_type", "arrival"),
        ).first()

        if existing:
            print(f"[Repository] Duplicate skipped: {clean_data.get('flight_number')} "
                  f"@ airport_id={clean_data.get('airport_id')} "
                  f"dep={clean_data.get('departure_time')} "
                  f"type={clean_data.get('flight_type')}")
            return existing

        flight = FlightModel(**clean_data)
        session.add(flight)
        session.flush()
        return flight

    # ── READ ALL ────────────────────────────────────
    def get_all(self, session: Session, airport_id: int = None) -> List[FlightModel]:
        query = (
            session.query(FlightModel)
            .options(joinedload(FlightModel.airline), joinedload(FlightModel.airport))
        )
        if airport_id:
            query = query.filter(FlightModel.airport_id == airport_id)
        return query.all()

    # ── READ ONE ────────────────────────────────────
    def get_by_id(self, session: Session, flight_id: int) -> Optional[FlightModel]:
        return (
            session.query(FlightModel)
            .options(joinedload(FlightModel.airline), joinedload(FlightModel.airport))
            .filter_by(id=flight_id)
            .first()
        )

    # ── UPDATE ──────────────────────────────────────
    def update(self, session: Session, flight_id: int, update_data: dict) -> Optional[FlightModel]:
        flight = session.query(FlightModel).filter_by(id=flight_id).first()
        if not flight:
            return None
        if "airline_code" in update_data:
            airline_code = update_data.pop("airline_code")
            airline = session.query(AirlineModel).filter_by(code=airline_code).first()
            if airline:
                flight.airline_id = airline.id
        for key, value in update_data.items():
            if hasattr(flight, key):
                setattr(flight, key, value)
        session.flush()
        return (
            session.query(FlightModel)
            .options(joinedload(FlightModel.airline), joinedload(FlightModel.airport))
            .filter_by(id=flight_id)
            .first()
        )

    # ── DELETE ──────────────────────────────────────
    def delete(self, session: Session, flight_id: int) -> bool:
        flight = session.query(FlightModel).filter_by(id=flight_id).first()
        if not flight:
            return False
        session.delete(flight)
        session.flush()
        return True

    # ── DELETE ALL ──────────────────────────────────
    def delete_all(self, session: Session, airport_id: int = None) -> int:
        query = session.query(FlightModel)
        if airport_id:
            query = query.filter(FlightModel.airport_id == airport_id)
        count = query.delete()
        session.flush()
        return count

    # ── CLEAR TODAY'S FLIGHTS ──────────────────────
    def clear_today_flights(self, session: Session, airport_id: int = None) -> int:
        """
        Called at midnight before publishing fresh daily schedule.
        Clears flights so the new day starts clean.
        """
        query = session.query(FlightModel)
        if airport_id:
            query = query.filter(FlightModel.airport_id == airport_id)
        count = query.delete()
        session.flush()
        print(f"[Repository] Cleared {count} flights before daily reset.")
        return count


class AirportRepository:

    def get_all(self, session: Session) -> List[AirportModel]:
        return session.query(AirportModel).all()

    def get_by_id(self, session: Session, airport_id: int) -> Optional[AirportModel]:
        return session.query(AirportModel).filter_by(id=airport_id).first()

    def get_by_code(self, session: Session, code: str) -> Optional[AirportModel]:
        return session.query(AirportModel).filter_by(code=code).first()


class UserRepository:

    def get_by_username(self, session: Session, username: str) -> Optional[UserModel]:
        return session.query(UserModel).filter_by(username=username).first()

    def get_by_id(self, session: Session, user_id: int) -> Optional[UserModel]:
        return session.query(UserModel).filter_by(id=user_id).first()

    def get_all(self, session: Session) -> List[UserModel]:
        return session.query(UserModel).all()

    def create(self, session: Session, user_data: dict) -> UserModel:
        user = UserModel(**user_data)
        session.add(user)
        session.flush()
        return user
