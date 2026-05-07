"""Vehicle API routes."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_customer
from database import get_db
from event_bus import publish_event
from models import Customer, Vehicle
from schemas import VehicleCreate, VehicleResponse, VehicleStatus, VehicleType, VehicleUpdate

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


class VehicleRouterSettings(BaseSettings):
    """Runtime settings for vehicle router infrastructure."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    REDIS_URL: str = "redis://redis:6379"
    ADMIN_EMAIL: str = "manager@rideswift.com"


@lru_cache(maxsize=1)
def get_vehicle_router_settings() -> VehicleRouterSettings:
    """Return cached settings for vehicle router."""
    return VehicleRouterSettings()


@lru_cache(maxsize=1)
def get_redis_client() -> aioredis.Redis:
    """Return shared async Redis client."""
    settings = get_vehicle_router_settings()
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


class VehicleStatusPatch(BaseModel):
    """Status update payload."""

    status: VehicleStatus


async def _clear_vehicle_cache(redis_client: aioredis.Redis) -> None:
    """Delete all vehicle list cache keys."""
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match="vehicles:*", count=500)
        if keys:
            await redis_client.delete(*keys)
        if cursor == 0:
            break


def _ensure_admin(customer: Customer) -> None:
    """Allow only admin customer to create vehicles."""
    settings = get_vehicle_router_settings()
    if customer.email != settings.ADMIN_EMAIL:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")


@router.get("/", response_model=list[VehicleResponse])
async def list_vehicles(
    db: Annotated[AsyncSession, Depends(get_db)],
    vehicle_type: Annotated[VehicleType | None, Query(alias="type")] = None,
    status_filter: Annotated[VehicleStatus | None, Query(alias="status")] = None,
    location: str | None = Query(default=None),
) -> list[Vehicle] | list[dict]:
    """List vehicles with Redis cache fallback."""
    redis_client = get_redis_client()
    cache_key = f"vehicles:{vehicle_type.value if vehicle_type else 'all'}:{status_filter.value if status_filter else 'all'}:{location or 'all'}"

    cached = await redis_client.get(cache_key)
    if cached:
        payload = json.loads(cached)
        if isinstance(payload, list):
            return payload

    stmt = select(Vehicle)
    if vehicle_type is not None:
        stmt = stmt.where(Vehicle.type == vehicle_type.value)
    if status_filter is not None:
        stmt = stmt.where(Vehicle.status == status_filter.value)
    if location:
        stmt = stmt.where(Vehicle.location == location)

    try:
        result = await db.execute(stmt.order_by(Vehicle.created_at.desc()))
        vehicles = list(result.scalars().all())
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch vehicles",
        ) from exc

    cache_payload = [VehicleResponse.model_validate(vehicle).model_dump(mode="json") for vehicle in vehicles]
    await redis_client.setex(cache_key, 30, json.dumps(cache_payload))
    return vehicles


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(vehicle_id: UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> Vehicle:
    """Get single vehicle by id."""
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


@router.patch("/{vehicle_id}/status", response_model=VehicleResponse)
async def patch_vehicle_status(
    vehicle_id: UUID,
    payload: VehicleStatusPatch,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Vehicle:
    """Update vehicle status, clear cache, and publish realtime event."""
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    vehicle.status = payload.status.value
    redis_client = get_redis_client()
    try:
        await db.flush()
        await db.commit()
        await db.refresh(vehicle)
        await _clear_vehicle_cache(redis_client)
        await redis_client.publish(
            "inventory:updates",
            json.dumps(
                {
                    "type": "vehicle_status_updated",
                    "vehicle_id": str(vehicle.id),
                    "status": vehicle.status,
                    "location": vehicle.location,
                }
            ),
        )
        publish_event(
            "vehicle.status.updated",
            {"vehicle_id": str(vehicle.id), "status": vehicle.status, "location": vehicle.location},
        )
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update vehicle status",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event streaming unavailable",
        ) from exc

    return vehicle


@router.post("/", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    payload: VehicleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_customer: Annotated[Customer, Depends(get_current_customer)],
) -> Vehicle:
    """Create vehicle (admin-only) and clear inventory cache."""
    _ensure_admin(current_customer)

    vehicle = Vehicle(
        type=payload.type.value,
        plate=payload.plate,
        brand=payload.brand,
        model_name=payload.model_name,
        status=payload.status.value,
        location=payload.location,
        daily_rate=payload.daily_rate,
        image_url=payload.image_url,
    )
    db.add(vehicle)

    redis_client = get_redis_client()
    try:
        await db.flush()
        await db.commit()
        await db.refresh(vehicle)
        await _clear_vehicle_cache(redis_client)
        publish_event(
            "vehicle.created",
            {
                "vehicle_id": str(vehicle.id),
                "type": vehicle.type,
                "brand": vehicle.brand,
                "model_name": vehicle.model_name,
                "status": vehicle.status,
            },
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle with this plate already exists",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create vehicle",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event streaming unavailable",
        ) from exc

    return vehicle
