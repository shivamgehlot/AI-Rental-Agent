"""Vehicle API routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from event_bus import publish_event
from metrics import refresh_active_vehicles_count
from models import Vehicle
from schemas import VehicleResponse, VehicleStatus

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=list[VehicleResponse])
async def list_vehicles(
    db: Annotated[AsyncSession, Depends(get_db)],
    vehicle_type: Annotated[str | None, Query(alias="type")] = None,
    status_filter: Annotated[VehicleStatus | None, Query(alias="status")] = None,
    location: str | None = None,
) -> list[Vehicle]:
    """List vehicles with optional filters."""
    stmt = select(Vehicle)
    if vehicle_type:
        stmt = stmt.where(Vehicle.type == vehicle_type)
    if status_filter:
        stmt = stmt.where(Vehicle.status == status_filter.value)
    if location:
        stmt = stmt.where(Vehicle.location == location)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(vehicle_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> Vehicle:
    """Fetch one vehicle by ID."""
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


@router.patch("/{vehicle_id}/status", response_model=VehicleResponse)
async def update_vehicle_status(
    vehicle_id: UUID,
    status_value: VehicleStatus = Query(alias="status"),
    db: AsyncSession = Depends(get_db),
) -> Vehicle:
    """Update a vehicle status."""
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    vehicle.status = status_value.value
    try:
        await db.flush()
        publish_event(
            "vehicle.status.updated",
            {"vehicle_id": str(vehicle.id), "status": vehicle.status},
        )
        await db.commit()
        await db.refresh(vehicle)
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
            detail="Failed to update vehicle status",
        ) from exc

    return vehicle
