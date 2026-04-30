"""
Pydantic schemas for request/response validation and serialization.
Covers Auth, Users, Airports, Airlines, and Flights.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ──────────────────────────────────────────────
#  Auth Schemas
# ──────────────────────────────────────────────

class LoginSchema(BaseModel):
    """Schema for login request."""
    username: str = Field(..., example="admin")
    password: str = Field(..., example="admin123")


class TokenSchema(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str
    username: str
    airport_id: Optional[int] = None  # None for admin


class UserCreateSchema(BaseModel):
    """Schema for registering a new user (admin only)."""
    username: str = Field(..., example="john_staff")
    password: str = Field(..., example="securepass123")
    email: str = Field(..., example="john@example.com")
    full_name: str = Field(..., example="John Doe")
    role: str = Field(default="viewer", example="staff")  # admin, staff, viewer
    airport_id: Optional[int] = Field(default=None, example=1)  # Required for staff/viewer


class UserResponseSchema(BaseModel):
    """Schema for user response."""
    id: int
    username: str
    email: str
    full_name: str
    role: str
    airport_id: Optional[int] = None
    created_at: Optional[datetime] = None
    is_active: bool = True

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
#  Airport Schemas
# ──────────────────────────────────────────────

class AirportResponseSchema(BaseModel):
    """Schema for airport response."""
    id: int
    name: str
    code: str
    city: str

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
#  Flight Schemas
# ──────────────────────────────────────────────

class FlightCreateSchema(BaseModel):
    """Schema for creating a new flight (POST request body)."""
    flight_number: str = Field(..., example="6E-201")
    airline_code: str = Field(..., example="6E")
    airport_id: Optional[int] = Field(default=None, example=1)
    origin: str = Field(..., example="Delhi (DEL)")
    destination: str = Field(..., example="Navi Mumbai (NMIA)")
    departure_time: str = Field(..., example="06:30")
    arrival_time: str = Field(..., example="08:45")
    gate_number: str = Field(..., example="G12")
    terminal_number: str = Field(..., example="T1")
    status: str = Field(default="Scheduled")
    flight_type: str = Field(default="arrival", example="arrival")  # arrival, departure, cargo


class FlightUpdateSchema(BaseModel):
    """Schema for updating a flight (PUT request body). All fields optional."""
    flight_number: Optional[str] = None
    airline_code: Optional[str] = None
    airport_id: Optional[int] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    gate_number: Optional[str] = None
    terminal_number: Optional[str] = None
    status: Optional[str] = None
    flight_type: Optional[str] = None


class FlightResponseSchema(BaseModel):
    """Schema for flight response (returned by GET endpoints)."""
    id: int
    flight_number: str
    airline_code: str
    airline_name: str
    airport_id: int
    airport_code: str
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    gate_number: str
    terminal_number: str
    status: str
    flight_type: str

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
#  Serializer Utility Class
# ──────────────────────────────────────────────

class FlightSerializer:
    """
    Utility class to convert between ORM models, domain objects, and API schemas.
    Follows OOP principles as required.
    """

    @staticmethod
    def orm_to_response(flight_model) -> dict:
        """Convert a FlightModel ORM instance to a response dictionary."""
        return {
            "id": flight_model.id,
            "flight_number": flight_model.flight_number,
            "airline_code": flight_model.airline.code if flight_model.airline else "",
            "airline_name": flight_model.airline.name if flight_model.airline else "",
            "airport_id": flight_model.airport_id,
            "airport_code": flight_model.airport.code if flight_model.airport else "",
            "origin": flight_model.origin,
            "destination": flight_model.destination,
            "departure_time": flight_model.departure_time,
            "arrival_time": flight_model.arrival_time,
            "gate_number": flight_model.gate_number,
            "terminal_number": flight_model.terminal_number,
            "status": flight_model.status,
            "flight_type": flight_model.flight_type or "arrival",
        }

    @staticmethod
    def schema_to_dict(schema: FlightCreateSchema) -> dict:
        """Convert a Pydantic create schema to a plain dict."""
        return schema.model_dump()

    @staticmethod
    def update_schema_to_dict(schema: FlightUpdateSchema) -> dict:
        """Convert a Pydantic update schema to a dict, excluding unset fields."""
        return schema.model_dump(exclude_unset=True)


class UserSerializer:
    """Utility class to convert UserModel ORM instances to response dicts."""

    @staticmethod
    def orm_to_response(user_model) -> dict:
        """Convert a UserModel ORM instance to a response dictionary."""
        return {
            "id": user_model.id,
            "username": user_model.username,
            "email": user_model.email,
            "full_name": user_model.full_name,
            "role": user_model.role,
            "airport_id": user_model.airport_id,  # None for admin
            "created_at": str(user_model.created_at) if user_model.created_at else None,
            "is_active": getattr(user_model, "is_active", True),
        }
