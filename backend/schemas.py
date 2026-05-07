"""Pydantic v2 schemas for RideSwift backend."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class VehicleStatus(str, Enum):
    """Valid vehicle lifecycle states."""

    available = "available"
    rented = "rented"
    maintenance = "maintenance"


class VehicleType(str, Enum):
    """Supported vehicle categories."""

    sedan = "sedan"
    suv = "suv"
    hatchback = "hatchback"
    ev = "ev"
    bike = "bike"


class BookingStatus(str, Enum):
    """Valid booking states."""

    pending = "pending"
    confirmed = "confirmed"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class VehicleBase(BaseModel):
    """Base fields shared by vehicle schemas."""

    type: VehicleType
    plate: str = Field(min_length=1, max_length=20)
    brand: str = Field(min_length=1, max_length=50)
    model_name: str = Field(min_length=1, max_length=50)
    status: VehicleStatus = VehicleStatus.available
    location: str = Field(min_length=1, max_length=100)
    daily_rate: Decimal = Field(gt=0)
    image_url: str | None = Field(default=None, max_length=300)


class VehicleCreate(VehicleBase):
    """Payload for creating a vehicle."""


class VehicleUpdate(BaseModel):
    """Payload for patching vehicle fields."""

    type: VehicleType | None = None
    plate: str | None = Field(default=None, min_length=1, max_length=20)
    brand: str | None = Field(default=None, min_length=1, max_length=50)
    model_name: str | None = Field(default=None, min_length=1, max_length=50)
    status: VehicleStatus | None = None
    location: str | None = Field(default=None, min_length=1, max_length=100)
    daily_rate: Decimal | None = Field(default=None, gt=0)
    image_url: str | None = Field(default=None, max_length=300)


class VehicleResponse(VehicleBase):
    """Vehicle response object."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime


class CustomerBase(BaseModel):
    """Base customer fields."""

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=20)


class CustomerCreate(CustomerBase):
    """Payload for creating customer accounts."""

    password: str = Field(min_length=8, max_length=128)


class CustomerResponse(CustomerBase):
    """Customer response without password/hash fields."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    preferences: dict | None = None
    loyalty_points: int
    created_at: datetime


class BookingCreate(BaseModel):
    """Payload for creating a booking."""

    customer_id: UUID
    vehicle_id: UUID
    pickup_date: datetime
    return_date: datetime
    notes: str | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> BookingCreate:
        """Validate booking pickup/return dates."""
        if self.return_date <= self.pickup_date:
            raise ValueError("return_date must be > pickup_date")
        if self.pickup_date.date() < date.today():
            raise ValueError("pickup_date must be >= today")
        return self


class BookingUpdate(BaseModel):
    """Payload for updating booking state/details."""

    status: BookingStatus | None = None
    actual_return_date: datetime | None = None
    notes: str | None = None
    insurance_validated: bool | None = None


class BookingResponse(BaseModel):
    """Booking response including nested customer and vehicle details."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    vehicle_id: UUID
    pickup_date: datetime
    return_date: datetime
    actual_return_date: datetime | None = None
    status: BookingStatus
    total_amount: Decimal
    insurance_validated: bool
    notes: str | None = None
    created_at: datetime
    vehicle: VehicleResponse
    customer: CustomerResponse


class LoginRequest(BaseModel):
    """Login request payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    """Auth token response payload."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
