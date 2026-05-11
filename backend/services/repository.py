"""
services/repository.py
========================
Data Access Layer — all raw SQLAlchemy queries live here.
No business logic, no HTTP concerns, no role checks.
"""

from sqlalchemy.orm import Session, joinedload
from models.models import FlightModel, AirlineModel, AirportModel, UserModel, CarouselChangeLog
from typing import List, Optional


class FlightRepository:
    """
    Handles all database operations for the flights table.
    """

    def __init__(self):
        pass

    # ── CREATE ────────────────────────────────────────────────────────────────

    def create(self, session: Session, flight_data: dict) -> FlightModel:
        clean_data = {
            k: v for k, v in flight_data.items()
            if not k.startswith("_") and k not in ("batch_id", "batch_name")
        }

        if "airline_code" in clean_data:
            airline_code = clean_data.pop("airline_code")
            airline = session.query(AirlineModel).filter_by(code=airline_code).first()
            if airline:
                clean_data["airline_id"] = airline.id
            else:
                print(f"[Repository] Unknown airline code: {airline_code}, skipping.")
                return None

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

    # ── READ ALL ──────────────────────────────────────────────────────────────

    def get_all(self, session: Session, airport_id: int = None) -> List[FlightModel]:
        query = (
            session.query(FlightModel)
            .options(
                joinedload(FlightModel.airline),
                joinedload(FlightModel.airport)
            )
        )
        if airport_id:
            query = query.filter(FlightModel.airport_id == airport_id)
        return query.all()

    # ── READ ONE ──────────────────────────────────────────────────────────────

    def get_by_id(self, session: Session, flight_id: int) -> Optional[FlightModel]:
        return (
            session.query(FlightModel)
            .options(
                joinedload(FlightModel.airline),
                joinedload(FlightModel.airport)
            )
            .filter_by(id=flight_id)
            .first()
        )

    # ── UPDATE ────────────────────────────────────────────────────────────────

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

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete(self, session: Session, flight_id: int) -> bool:
        flight = session.query(FlightModel).filter_by(id=flight_id).first()
        if not flight:
            return False
        session.delete(flight)
        session.flush()
        return True

    def delete_all(self, session: Session, airport_id: int = None) -> int:
        query = session.query(FlightModel)
        if airport_id:
            query = query.filter(FlightModel.airport_id == airport_id)
        count = query.delete()
        session.flush()
        return count

    def clear_today_flights(self, session: Session, airport_id: int = None) -> int:
        query = session.query(FlightModel)
        if airport_id:
            query = query.filter(FlightModel.airport_id == airport_id)
        count = query.delete()
        session.flush()
        print(f"[Repository] Cleared {count} flights before daily reset.")
        return count


class CarouselRepository:
    """
    Handles all DB operations for the carousel_change_log table.

    Keeps the full history of every carousel assignment and change,
    used for audit display in the frontend BHS log panel and for
    admin oversight of operational decisions.
    """

    def log_change(
        self,
        session: Session,
        flight_id: int,
        flight_number: str,
        old_carousel: Optional[str],
        new_carousel: str,
        changed_by: str,
        reason: Optional[str] = None,
        event_type: str = "CAROUSEL_ASSIGNED",
    ) -> CarouselChangeLog:
        """
        Insert a new carousel change log entry.
        Called by the service layer on every assignment or manual override.
        """
        from datetime import datetime
        log = CarouselChangeLog(
            flight_id=flight_id,
            flight_number=flight_number,
            old_carousel=old_carousel,
            new_carousel=new_carousel,
            changed_by=changed_by,
            changed_at=datetime.utcnow(),
            reason=reason,
            event_type=event_type,
        )
        session.add(log)
        session.flush()
        return log

    def get_by_flight(self, session: Session, flight_id: int) -> List[CarouselChangeLog]:
        """Return all log entries for a specific flight, newest first."""
        return (
            session.query(CarouselChangeLog)
            .filter_by(flight_id=flight_id)
            .order_by(CarouselChangeLog.changed_at.desc())
            .all()
        )

    def get_recent(self, session: Session, limit: int = 20) -> List[CarouselChangeLog]:
        """
        Return the most recent carousel events across all flights.
        Used by the BHS log panel on the frontend dashboard.
        """
        return (
            session.query(CarouselChangeLog)
            .order_by(CarouselChangeLog.changed_at.desc())
            .limit(limit)
            .all()
        )


class AirportRepository:
    """Read-only data access for the airports table."""

    def get_all(self, session: Session) -> List[AirportModel]:
        return session.query(AirportModel).all()

    def get_by_id(self, session: Session, airport_id: int) -> Optional[AirportModel]:
        return session.query(AirportModel).filter_by(id=airport_id).first()

    def get_by_code(self, session: Session, code: str) -> Optional[AirportModel]:
        return session.query(AirportModel).filter_by(code=code).first()


class UserRepository:
    """Data access methods for the users table."""

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