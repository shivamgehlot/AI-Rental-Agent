"""Customer API routes."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_customer
from database import get_db
from models import Booking, Customer, Vehicle
from schemas import BookingResponse, CustomerResponse

router = APIRouter(prefix="/api/customers", tags=["customers"])


class PreferencesUpdateRequest(BaseModel):
    """Incoming preferences update payload."""

    preferred_type: str | None = None


def _ensure_self_access(customer_id: UUID, current_customer: Customer) -> None:
    """Ensure authenticated customer can access only their own profile."""
    if customer_id != current_customer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer_profile(
    customer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_customer: Annotated[Customer, Depends(get_current_customer)],
) -> Customer:
    """Return authenticated customer's profile."""
    _ensure_self_access(customer_id, current_customer)
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.get("/{customer_id}/bookings", response_model=list[BookingResponse])
async def get_customer_bookings(
    customer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_customer: Annotated[Customer, Depends(get_current_customer)],
) -> list[Booking]:
    """Return authenticated customer's bookings with nested vehicle details."""
    _ensure_self_access(customer_id, current_customer)
    try:
        result = await db.execute(
            select(Booking)
            .where(Booking.customer_id == customer_id)
            .order_by(Booking.created_at.desc())
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch customer bookings",
        ) from exc
    return list(result.scalars().all())


@router.patch("/{customer_id}/preferences", response_model=CustomerResponse)
async def update_customer_preferences(
    customer_id: UUID,
    payload: PreferencesUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_customer: Annotated[Customer, Depends(get_current_customer)],
) -> Customer:
    """Update preferences JSON with auto-calculated preferred_type and average_spend."""
    _ensure_self_access(customer_id, current_customer)

    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    try:
        booking_rows = await db.execute(
            select(Booking.total_amount, Vehicle.type)
            .join(Vehicle, Vehicle.id == Booking.vehicle_id)
            .where(Booking.customer_id == customer_id)
        )
        records = booking_rows.all()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate preferences",
        ) from exc

    spends = [Decimal(str(record[0])) for record in records if record[0] is not None]
    average_spend = float(sum(spends) / len(spends)) if spends else 0.0

    type_counter = Counter(record[1] for record in records if record[1])
    auto_preferred_type = type_counter.most_common(1)[0][0] if type_counter else None
    preferred_type = payload.preferred_type or auto_preferred_type

    customer.preferences = {
        "preferred_type": preferred_type,
        "average_spend": round(average_spend, 2),
    }
    try:
        await db.flush()
        await db.commit()
        await db.refresh(customer)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update customer preferences",
        ) from exc

    return customer
