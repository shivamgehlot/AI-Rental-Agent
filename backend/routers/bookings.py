"""Booking API routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import and_, not_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_customer
from database import get_db
from event_bus import publish_event
from models import Booking, Customer, Vehicle
from schemas import BookingCreate, BookingResponse, BookingStatus, BookingUpdate

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


class BookingRouterSettings(BaseSettings):
    """Runtime settings for booking router."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    REDIS_URL: str = "redis://redis:6379"


@lru_cache(maxsize=1)
def get_booking_router_settings() -> BookingRouterSettings:
    """Return cached booking router settings."""
    return BookingRouterSettings()


@lru_cache(maxsize=1)
def get_redis_client() -> aioredis.Redis:
    """Return shared Redis client."""
    settings = get_booking_router_settings()
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def _clear_vehicle_cache(redis_client: aioredis.Redis) -> None:
    """Clear cached vehicle listing keys."""
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match="vehicles:*", count=500)
        if keys:
            await redis_client.delete(*keys)
        if cursor == 0:
            break


def _calculate_days(pickup_date: datetime, return_date: datetime) -> int:
    """Calculate billable booking days (minimum one day)."""
    delta = return_date - pickup_date
    return max(1, delta.days + (1 if delta.seconds > 0 else 0))


async def _get_customer_booking_or_404(
    db: AsyncSession,
    booking_id: UUID,
    customer_id: UUID,
) -> Booking:
    """Get booking belonging to current customer or raise 404."""
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.customer_id == customer_id)
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking


@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: BookingCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_customer: Annotated[Customer, Depends(get_current_customer)],
) -> Booking:
    """Create booking with overlap checks and inventory/event updates."""
    if payload.customer_id != current_customer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create booking for another customer")

    vehicle = await db.get(Vehicle, payload.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if vehicle.status != "available":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle not available for selected dates")

    overlap_stmt = select(Booking.id).where(
        Booking.vehicle_id == payload.vehicle_id,
        Booking.status.in_([BookingStatus.confirmed.value, BookingStatus.active.value]),
        not_(
            or_(
                Booking.return_date <= payload.pickup_date,
                Booking.pickup_date >= payload.return_date,
            )
        ),
    )
    overlap_result = await db.execute(overlap_stmt)
    if overlap_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle not available for selected dates")

    number_of_days = _calculate_days(payload.pickup_date, payload.return_date)
    total_amount = Decimal(str(vehicle.daily_rate)) * Decimal(number_of_days)

    booking = Booking(
        customer_id=current_customer.id,
        vehicle_id=payload.vehicle_id,
        pickup_date=payload.pickup_date,
        return_date=payload.return_date,
        status=BookingStatus.pending.value,
        total_amount=total_amount,
        notes=payload.notes,
        insurance_validated=False,
    )
    booking.customer = current_customer
    booking.vehicle = vehicle
    vehicle.status = "rented"
    db.add(booking)

    redis_client = get_redis_client()
    try:
        await db.flush()
        await db.commit()
        await db.refresh(booking)
        await _clear_vehicle_cache(redis_client)
        publish_event(
            "booking.created",
            {
                "booking_id": str(booking.id),
                "customer_id": str(booking.customer_id),
                "vehicle_id": str(booking.vehicle_id),
                "customer_name": current_customer.name,
                "vehicle_info": f"{vehicle.brand} {vehicle.model_name} ({vehicle.plate})",
                "pickup_date": booking.pickup_date.isoformat(),
                "return_date": booking.return_date.isoformat(),
                "total_amount": str(booking.total_amount),
            },
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create booking") from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event stream unavailable",
        ) from exc

    return booking


@router.get("/", response_model=list[BookingResponse])
async def list_my_bookings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_customer: Annotated[Customer, Depends(get_current_customer)],
    status_filter: BookingStatus | None = Query(default=None, alias="status"),
) -> list[Booking]:
    """List current customer's bookings, optionally filtered by status."""
    filters = [Booking.customer_id == current_customer.id]
    if status_filter is not None:
        filters.append(Booking.status == status_filter.value)
    stmt = select(Booking).where(and_(*filters)).order_by(Booking.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_my_booking(
    booking_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_customer: Annotated[Customer, Depends(get_current_customer)],
) -> Booking:
    """Get a booking by id that belongs to current customer."""
    return await _get_customer_booking_or_404(db, booking_id, current_customer.id)


@router.patch("/{booking_id}", response_model=BookingResponse)
async def update_booking(
    booking_id: UUID,
    payload: BookingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_customer: Annotated[Customer, Depends(get_current_customer)],
) -> Booking:
    """Update booking lifecycle fields and publish state events."""
    booking = await _get_customer_booking_or_404(db, booking_id, current_customer.id)
    vehicle = await db.get(Vehicle, booking.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    if payload.notes is not None:
        booking.notes = payload.notes
    if payload.insurance_validated is not None:
        booking.insurance_validated = payload.insurance_validated
    if payload.actual_return_date is not None:
        booking.actual_return_date = payload.actual_return_date

    event_topic: str | None = None
    event_payload: dict[str, str] | None = None

    if payload.status is not None:
        booking.status = payload.status.value
        if payload.status == BookingStatus.confirmed:
            event_topic = "booking.confirmed"
            event_payload = {"booking_id": str(booking.id), "vehicle_id": str(booking.vehicle_id)}
        elif payload.status == BookingStatus.cancelled:
            vehicle.status = "available"
            event_topic = "booking.cancelled"
            event_payload = {"booking_id": str(booking.id), "vehicle_id": str(booking.vehicle_id)}
        elif payload.status == BookingStatus.completed:
            vehicle.status = "available"
            booking.actual_return_date = datetime.now(UTC)
            event_topic = "booking.completed"
            event_payload = {"booking_id": str(booking.id), "vehicle_id": str(booking.vehicle_id)}

    redis_client = get_redis_client()
    try:
        await db.flush()
        await db.commit()
        await db.refresh(booking)
        await _clear_vehicle_cache(redis_client)
        if event_topic and event_payload:
            publish_event(event_topic, event_payload)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update booking") from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event stream unavailable",
        ) from exc

    await redis_client.publish(
        "inventory:updates",
        json.dumps(
            {
                "type": "booking_updated",
                "booking_id": str(booking.id),
                "vehicle_id": str(booking.vehicle_id),
                "status": booking.status,
            }
        ),
    )
    return booking
