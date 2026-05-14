"""
Pydantic schemas for request/response validation and serialization.
Covers Auth, Users, Airports, Airlines, Flights, and Carousel.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ──────────────────────────────────────────────
#  Auth Schemas
# ──────────────────────────────────────────────

class LoginSchema(BaseModel):
    username: str = Field(..., example="admin")
    password: str = Field(..., example="admin123")


class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str
    username: str
    airport_id: Optional[int] = None


class UserCreateSchema(BaseModel):
    username: str = Field(..., example="john_staff")
    password: str = Field(..., example="securepass123")
    email: str = Field(..., example="john@example.com")
    full_name: str = Field(..., example="John Doe")
    role: str = Field(default="viewer", example="staff")
    airport_id: Optional[int] = Field(default=None, example=1)


class UserResponseSchema(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    airport_id: Optional[int] = None
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    last_password_changed_at: Optional[datetime] = None
    is_active: bool = True

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
#  Airport Schemas
# ──────────────────────────────────────────────

class AirportResponseSchema(BaseModel):
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
    flight_type: str = Field(default="arrival", example="arrival")


class FlightUpdateSchema(BaseModel):
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
    carousel_number: Optional[str] = None
    
    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
#  Carousel Schemas
# ──────────────────────────────────────────────

class CarouselUpdateSchema(BaseModel):
    """
    Schema for manually overriding a carousel assignment.
    Used by PUT /flights/{id}/carousel (admin/staff only).

    reason is optional but strongly recommended — it gets logged
    in carousel_change_log and published to RabbitMQ so the BHS
    can attach context to the CAROUSEL_CHANGED event.
    """
    carousel_number: str = Field(..., example="C5")
    reason: Optional[str] = Field(
        default=None,
        example="Mechanical fault on C3 — rerouting to C5"
    )


class CarouselLogResponseSchema(BaseModel):
    """Schema for a single carousel change log entry."""
    id: int
    flight_id: int
    flight_number: str
    old_carousel: Optional[str] = None
    new_carousel: str
    changed_by: str
    changed_at: datetime
    reason: Optional[str] = None
    event_type: str

    class Config:
        from_attributes = True


# ──────────────────────────────────────────────
#  Serializer Utility Classes
# ──────────────────────────────────────────────

class FlightSerializer:
    """
    Utility class to convert between ORM models, domain objects, and API schemas.
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
            "carousel_number": getattr(flight_model, "carousel_number", None),
        }

    @staticmethod
    def schema_to_dict(schema: FlightCreateSchema) -> dict:
        return schema.model_dump()

    @staticmethod
    def update_schema_to_dict(schema: FlightUpdateSchema) -> dict:
        return schema.model_dump(exclude_unset=True)


class UserSerializer:
    """Utility class to convert UserModel ORM instances to response dicts."""

    @staticmethod
    def orm_to_response(user_model) -> dict:
        return {
            "id": user_model.id,
            "username": user_model.username,
            "email": user_model.email,
            "full_name": user_model.full_name,
            "role": user_model.role,
            "airport_id": user_model.airport_id,
            "created_at": str(user_model.created_at) if user_model.created_at else None,
            "last_login_at": str(user_model.last_login_at) if getattr(user_model, "last_login_at", None) else None,
            "last_password_changed_at": str(user_model.last_password_changed_at) if getattr(user_model, "last_password_changed_at", None) else None,
            "is_active": getattr(user_model, "is_active", True),
        }