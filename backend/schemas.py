"""Pydantic schemas for RideSwift backend APIs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class VehicleStatus(str, Enum):
    """Valid vehicle status values."""

    available = "available"
    rented = "rented"
    maintenance = "maintenance"


class BookingStatus(str, Enum):
    """Valid booking status values."""

    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"


class ORMBaseSchema(BaseModel):
    """Base schema configured for ORM model serialization."""

    model_config = ConfigDict(from_attributes=True)


class VehicleCreate(BaseModel):
    """Payload to create a vehicle."""

    type: str = Field(min_length=1, max_length=50)
    brand: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    plate_number: str = Field(min_length=1, max_length=50)
    location: str = Field(min_length=1, max_length=100)
    price_per_day: Decimal = Field(gt=0)
    status: VehicleStatus = VehicleStatus.available


class VehicleUpdate(BaseModel):
    """Payload to update a vehicle."""

    type: str | None = Field(default=None, min_length=1, max_length=50)
    brand: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    plate_number: str | None = Field(default=None, min_length=1, max_length=50)
    location: str | None = Field(default=None, min_length=1, max_length=100)
    price_per_day: Decimal | None = Field(default=None, gt=0)
    status: VehicleStatus | None = None


class VehicleResponse(ORMBaseSchema):
    """Vehicle API response model."""

    id: UUID
    type: str
    brand: str
    model: str
    plate_number: str
    location: str
    price_per_day: Decimal
    status: VehicleStatus
    created_at: datetime


class CustomerCreate(BaseModel):
    """Payload to create a customer."""

    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class CustomerUpdate(BaseModel):
    """Payload to update a customer."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    loyalty_points: int | None = Field(default=None, ge=0)


class CustomerResponse(ORMBaseSchema):
    """Customer API response model."""

    id: UUID
    full_name: str
    email: EmailStr
    phone: str | None
    loyalty_points: int
    created_at: datetime


class BookingCreate(BaseModel):
    """Payload to create a booking."""

    customer_id: UUID
    vehicle_id: UUID
    pickup_date: datetime
    return_date: datetime
    total_price: Decimal = Field(gt=0)
    status: BookingStatus = BookingStatus.pending
    notes: str | None = None

    @model_validator(mode="after")
    def validate_booking_dates(self) -> BookingCreate:
        """Ensure booking return date is after pickup date."""
        if self.return_date <= self.pickup_date:
            raise ValueError("return_date must be after pickup_date")
        return self


class BookingUpdate(BaseModel):
    """Payload to update a booking."""

    pickup_date: datetime | None = None
    return_date: datetime | None = None
    total_price: Decimal | None = Field(default=None, gt=0)
    status: BookingStatus | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_booking_dates(self) -> BookingUpdate:
        """Ensure booking return date is after pickup date when both are provided."""
        if (
            self.pickup_date is not None
            and self.return_date is not None
            and self.return_date <= self.pickup_date
        ):
            raise ValueError("return_date must be after pickup_date")
        return self


class BookingResponse(ORMBaseSchema):
    """Booking API response model."""

    id: UUID
    customer_id: UUID
    vehicle_id: UUID
    pickup_date: datetime
    return_date: datetime
    total_price: Decimal
    status: BookingStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class InsuranceDocumentCreate(BaseModel):
    """Payload to create an insurance document record."""

    customer_id: UUID
    file_name: str = Field(min_length=1, max_length=255)
    file_url: str = Field(min_length=1, max_length=512)


class InsuranceDocumentUpdate(BaseModel):
    """Payload to update an insurance document record."""

    file_name: str | None = Field(default=None, min_length=1, max_length=255)
    file_url: str | None = Field(default=None, min_length=1, max_length=512)


class InsuranceDocumentResponse(ORMBaseSchema):
    """Insurance document API response model."""

    id: UUID
    customer_id: UUID
    file_name: str
    file_url: str
    uploaded_at: datetime
