"""Booking API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from event_bus import publish_event
from metrics import record_booking_created, refresh_active_vehicles_count
from models import Booking, Customer, Vehicle
from schemas import BookingCreate, BookingResponse, BookingStatus, BookingUpdate

router = APIRouter(prefix="/bookings", tags=["bookings"], dependencies=[Depends(get_current_user)])


async def _has_booking_conflict(
    db: AsyncSession,
    vehicle_id: UUID,
    pickup_date: datetime,
    return_date: datetime,
    exclude_booking_id: UUID | None = None,
) -> bool:
    """Check if a booking collides with existing active bookings."""
    stmt = select(Booking.id).where(
        Booking.vehicle_id == vehicle_id,
        Booking.status.in_([BookingStatus.pending.value, BookingStatus.confirmed.value]),
        Booking.pickup_date < return_date,
        Booking.return_date > pickup_date,
    )
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)

    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: BookingCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Booking:
    """Create a booking with overbooking protection."""
    customer = await db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    vehicle = await db.get(Vehicle, payload.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    if vehicle.status != "available":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle is not available")

    if await _has_booking_conflict(db, payload.vehicle_id, payload.pickup_date, payload.return_date):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle already booked for these dates")

    booking = Booking(
        customer_id=payload.customer_id,
        vehicle_id=payload.vehicle_id,
        pickup_date=payload.pickup_date,
        return_date=payload.return_date,
        total_price=payload.total_price,
        status=payload.status.value,
        notes=payload.notes,
    )
    db.add(booking)

    try:
        await db.flush()
        publish_event(
            "booking.created",
            {
                "booking_id": str(booking.id),
                "customer_id": str(booking.customer_id),
                "vehicle_id": str(booking.vehicle_id),
                "pickup_date": booking.pickup_date.isoformat(),
                "return_date": booking.return_date.isoformat(),
            },
        )
        await db.commit()
        await db.refresh(booking)
        record_booking_created()
        await refresh_active_vehicles_count(db)
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event stream unavailable",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create booking",
        ) from exc
    return booking


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(booking_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> Booking:
    """Fetch one booking by ID."""
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking


@router.patch("/{booking_id}", response_model=BookingResponse)
async def update_booking(
    booking_id: UUID,
    payload: BookingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Booking:
    """Modify booking details."""
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    next_pickup = payload.pickup_date or booking.pickup_date
    next_return = payload.return_date or booking.return_date
    if next_return <= next_pickup:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="return_date must be after pickup_date",
        )

    if payload.pickup_date is not None:
        booking.pickup_date = payload.pickup_date
    if payload.return_date is not None:
        booking.return_date = payload.return_date
    if payload.total_price is not None:
        booking.total_price = payload.total_price
    if payload.notes is not None:
        booking.notes = payload.notes

    if payload.status is not None:
        booking.status = payload.status.value

    if await _has_booking_conflict(
        db,
        booking.vehicle_id,
        booking.pickup_date,
        booking.return_date,
        exclude_booking_id=booking.id,
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle already booked for these dates")

    try:
        await db.flush()
        publish_event(
            "booking.updated",
            {
                "booking_id": str(booking.id),
                "status": booking.status,
                "pickup_date": booking.pickup_date.isoformat(),
                "return_date": booking.return_date.isoformat(),
            },
        )
        if booking.status == BookingStatus.cancelled.value:
            publish_event("booking.cancelled", {"booking_id": str(booking.id), "vehicle_id": str(booking.vehicle_id)})
        if booking.status == BookingStatus.confirmed.value:
            publish_event("booking.confirmed", {"booking_id": str(booking.id), "customer_id": str(booking.customer_id)})
        await db.commit()
        await db.refresh(booking)
        await refresh_active_vehicles_count(db)
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event stream unavailable",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update booking",
        ) from exc
    return booking


@router.delete("/{booking_id}", response_model=BookingResponse)
async def cancel_booking(booking_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> Booking:
    """Cancel a booking without deleting the record."""
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    booking.status = BookingStatus.cancelled.value
    try:
        await db.flush()
        publish_event("booking.cancelled", {"booking_id": str(booking.id), "vehicle_id": str(booking.vehicle_id)})
        await db.commit()
        await db.refresh(booking)
        await refresh_active_vehicles_count(db)
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event stream unavailable",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel booking",
        ) from exc
    return booking


@router.get("", response_model=list[BookingResponse])
async def list_bookings(
    db: Annotated[AsyncSession, Depends(get_db)],
    pickup_from: datetime | None = Query(default=None),
    pickup_to: datetime | None = Query(default=None),
    return_from: datetime | None = Query(default=None),
    return_to: datetime | None = Query(default=None),
    status_filter: BookingStatus | None = Query(default=None, alias="status"),
) -> list[Booking]:
    """List bookings with optional date/status filters."""
    filters = []
    if pickup_from is not None:
        filters.append(Booking.pickup_date >= pickup_from)
    if pickup_to is not None:
        filters.append(Booking.pickup_date <= pickup_to)
    if return_from is not None:
        filters.append(Booking.return_date >= return_from)
    if return_to is not None:
        filters.append(Booking.return_date <= return_to)
    if status_filter is not None:
        filters.append(Booking.status == status_filter.value)

    stmt = select(Booking).order_by(Booking.pickup_date.desc())
    if filters:
        stmt = stmt.where(and_(*filters))

    result = await db.execute(stmt)
    return list(result.scalars().all())
