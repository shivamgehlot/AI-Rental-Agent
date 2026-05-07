"""Customer API routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from event_bus import publish_event
from models import Booking, Customer
from schemas import BookingResponse, CustomerCreate, CustomerResponse

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Customer:
    """Register a customer."""
    customer = Customer(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
    )
    db.add(customer)

    try:
        await db.flush()
        publish_event(
            "customer.created",
            {"customer_id": str(customer.id), "email": customer.email},
        )
        await db.commit()
        await db.refresh(customer)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Customer with this email already exists",
        ) from exc
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
            detail="Failed to create customer",
        ) from exc
    return customer


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> Customer:
    """Fetch one customer by ID."""
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.get("/{customer_id}/bookings", response_model=list[BookingResponse])
async def list_customer_bookings(
    customer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Booking]:
    """List bookings for a specific customer."""
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    result = await db.execute(
        select(Booking).where(Booking.customer_id == customer_id).order_by(Booking.pickup_date.desc())
    )
    return list(result.scalars().all())
