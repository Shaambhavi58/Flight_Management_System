"""
ORM Models and OOP Domain Classes for the Flight Management System.

ORM models (UserModel, AirportModel, AirlineModel, FlightModel) map to database tables.
Domain classes (User, Airport, Airline, Flight) encapsulate business data with OOP principles.
"""

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from core.database import Base
from datetime import datetime


# ──────────────────────────────────────────────
#  SQLAlchemy ORM Models (Database Layer)
# ──────────────────────────────────────────────

class UserModel(Base):
    """ORM model for the 'users' table."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="viewer")  # admin, staff, viewer
    airport_id = Column(Integer, ForeignKey("airports.id"), nullable=True)  # NULL for admin
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    creator = relationship("UserModel", remote_side=[id], foreign_keys=[created_by])
    airport = relationship("AirportModel", foreign_keys=[airport_id])

    def __repr__(self):
        return f"<UserModel(id={self.id}, username='{self.username}', role='{self.role}', airport_id={self.airport_id})>"


class AirportModel(Base):
    """ORM model for the 'airports' table."""
    __tablename__ = "airports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False, unique=True)
    code = Column(String(10), nullable=False, unique=True)   # IATA code
    city = Column(String(50), nullable=False)

    flights = relationship("FlightModel", back_populates="airport", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AirportModel(id={self.id}, name='{self.name}', code='{self.code}')>"


class AirlineModel(Base):
    """ORM model for the 'airlines' table."""
    __tablename__ = "airlines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    code = Column(String(5), nullable=False, unique=True)  # IATA code

    flights = relationship("FlightModel", back_populates="airline", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AirlineModel(id={self.id}, name='{self.name}', code='{self.code}')>"


class FlightModel(Base):
    """ORM model for the 'flights' table."""
    __tablename__ = "flights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    flight_number = Column(String(20), nullable=False)
    airline_id = Column(Integer, ForeignKey("airlines.id"), nullable=False)
    airport_id = Column(Integer, ForeignKey("airports.id"), nullable=False)
    origin = Column(String(100), nullable=False)
    destination = Column(String(100), nullable=False)
    departure_time = Column(String(10), nullable=False)   # HH:MM format
    arrival_time = Column(String(10), nullable=False)      # HH:MM format
    gate_number = Column(String(10), nullable=False)
    terminal_number = Column(String(5), nullable=False)    # T1, T2, T3
    status = Column(String(30), nullable=False, default="Scheduled")
    flight_type = Column(String(20), nullable=False, default="arrival")  # arrival, departure, cargo

    airline = relationship("AirlineModel", back_populates="flights")
    airport = relationship("AirportModel", back_populates="flights")

    __table_args__ = (
        UniqueConstraint(
            "flight_number", "departure_time", "airport_id", "flight_type",
            name="unique_flight_constraint"
        ),
    )

    def __repr__(self):
        return f"<FlightModel(id={self.id}, flight='{self.flight_number}', status='{self.status}')>"


# ──────────────────────────────────────────────
#  OOP Domain Classes (Business Layer)
# ──────────────────────────────────────────────

class User:
    """Domain class representing a User with encapsulation."""

    def __init__(
        self, username: str, email: str, full_name: str,
        role: str = "viewer", id: int = None, airport_id: int = None
    ):
        self._id = id
        self._username = username
        self._email = email
        self._full_name = full_name
        self._role = role
        self._airport_id = airport_id  # None for admin

    @property
    def id(self):
        return self._id

    @property
    def username(self):
        return self._username

    @property
    def email(self):
        return self._email

    @property
    def full_name(self):
        return self._full_name

    @property
    def role(self):
        return self._role

    @role.setter
    def role(self, value: str):
        allowed = ["admin", "staff", "viewer"]
        if value not in allowed:
            raise ValueError(f"Role must be one of {allowed}")
        self._role = value

    @property
    def airport_id(self):
        return self._airport_id

    def __str__(self):
        return f"{self._full_name} ({self._username}) - {self._role}"

    def __repr__(self):
        return f"User(username='{self._username}', role='{self._role}', airport_id={self._airport_id})"


class Airport:
    """Domain class representing an Airport with encapsulation."""

    def __init__(self, name: str, code: str, city: str, id: int = None):
        self._id = id
        self._name = name
        self._code = code
        self._city = city

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def code(self):
        return self._code

    @property
    def city(self):
        return self._city

    def __str__(self):
        return f"{self._name} ({self._code}) - {self._city}"

    def __repr__(self):
        return f"Airport(name='{self._name}', code='{self._code}')"


class Airline:
    """Domain class representing an Airline with encapsulation."""

    def __init__(self, name: str, code: str, id: int = None):
        self._id = id
        self._name = name
        self._code = code

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def code(self):
        return self._code

    def __str__(self):
        return f"{self._name} ({self._code})"

    def __repr__(self):
        return f"Airline(name='{self._name}', code='{self._code}')"


class Flight:
    """Domain class representing a Flight with encapsulation."""

    def __init__(
        self,
        flight_number: str,
        airline_code: str,
        origin: str,
        destination: str,
        departure_time: str,
        arrival_time: str,
        gate_number: str,
        terminal_number: str,
        status: str = "Scheduled",
        flight_type: str = "arrival",
        id: int = None,
        airline_name: str = None,
        airport_code: str = None,
    ):
        self._id = id
        self._flight_number = flight_number
        self._airline_code = airline_code
        self._airline_name = airline_name
        self._airport_code = airport_code
        self._origin = origin
        self._destination = destination
        self._departure_time = departure_time
        self._arrival_time = arrival_time
        self._gate_number = gate_number
        self._terminal_number = terminal_number
        self._status = status
        self._flight_type = flight_type

    # --- Properties ---
    @property
    def id(self):
        return self._id

    @property
    def flight_number(self):
        return self._flight_number

    @property
    def airline_code(self):
        return self._airline_code

    @property
    def airline_name(self):
        return self._airline_name

    @property
    def airport_code(self):
        return self._airport_code

    @property
    def origin(self):
        return self._origin

    @property
    def destination(self):
        return self._destination

    @property
    def departure_time(self):
        return self._departure_time

    @property
    def arrival_time(self):
        return self._arrival_time

    @property
    def gate_number(self):
        return self._gate_number

    @property
    def terminal_number(self):
        return self._terminal_number

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value: str):
        allowed = ["Scheduled", "Boarding", "Departed", "Arrived", "Delayed", "Cancelled"]
        if value not in allowed:
            raise ValueError(f"Status must be one of {allowed}")
        self._status = value

    @property
    def flight_type(self):
        return self._flight_type

    @flight_type.setter
    def flight_type(self, value: str):
        allowed = ["arrival", "departure", "cargo"]
        if value not in allowed:
            raise ValueError(f"Flight type must be one of {allowed}")
        self._flight_type = value

    def to_dict(self) -> dict:
        """Serialize the flight to a dictionary."""
        return {
            "id": self._id,
            "flight_number": self._flight_number,
            "airline_code": self._airline_code,
            "airline_name": self._airline_name,
            "airport_code": self._airport_code,
            "origin": self._origin,
            "destination": self._destination,
            "departure_time": self._departure_time,
            "arrival_time": self._arrival_time,
            "gate_number": self._gate_number,
            "terminal_number": self._terminal_number,
            "status": self._status,
            "flight_type": self._flight_type,
        }

    def __str__(self):
        return (
            f"Flight {self._flight_number} | {self._origin} -> {self._destination} | "
            f"Dep: {self._departure_time} | Gate: {self._gate_number} | "
            f"Terminal: {self._terminal_number} | Status: {self._status}"
        )

    def __repr__(self):
        return f"Flight(flight_number='{self._flight_number}', status='{self._status}')"
