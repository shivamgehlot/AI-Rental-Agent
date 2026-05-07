"""Personalization tools for RideSwift booking agent."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from functools import lru_cache
from statistics import mean
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PersonalizationSettings(BaseSettings):
    """Settings for backend integration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    BACKEND_API_URL: str = "http://backend:8000"
    BACKEND_API_TOKEN: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> PersonalizationSettings:
    """Return cached settings."""
    return PersonalizationSettings()


class RecommendationDates(BaseModel):
    """Date range for recommendations."""

    pickup_date: datetime
    return_date: datetime


class CustomerPreferences(BaseModel):
    """Customer preference summary."""

    model_config = ConfigDict(from_attributes=True)
    customer_id: UUID
    preferred_vehicle_type: str | None
    average_spend: float
    loyalty_points: int
    total_bookings: int


def _headers() -> dict[str, str]:
    """Build backend authorization headers if configured."""
    settings = get_settings()
    if settings.BACKEND_API_TOKEN:
        return {"Authorization": f"Bearer {settings.BACKEND_API_TOKEN}"}
    return {}


async def _fetch_customer_bookings(customer_id: UUID) -> list[dict[str, Any]]:
    """Fetch customer booking history from backend."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/api/customers/{customer_id}/bookings",
            headers=_headers(),
        )
        response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


async def _fetch_customer(customer_id: UUID) -> dict[str, Any]:
    """Fetch customer details from backend."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/api/customers/{customer_id}",
            headers=_headers(),
        )
        response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def _fetch_vehicle(vehicle_id: UUID) -> dict[str, Any]:
    """Fetch one vehicle from backend."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/api/vehicles/{vehicle_id}",
            headers=_headers(),
        )
        response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


async def _fetch_available_vehicles(vehicle_type: str | None = None) -> list[dict[str, Any]]:
    """Fetch available vehicles, optionally by type."""
    settings = get_settings()
    params: dict[str, str] = {"status": "available"}
    if vehicle_type:
        params["type"] = vehicle_type
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/api/vehicles/",
            params=params,
            headers=_headers(),
        )
        response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


async def get_customer_preferences(customer_id: str) -> str:
    """Return preferred vehicle type, average spend, and loyalty points."""
    customer_uuid = UUID(customer_id)
    bookings = await _fetch_customer_bookings(customer_uuid)
    customer = await _fetch_customer(customer_uuid)

    vehicle_types: list[str] = []
    for booking in bookings:
        vehicle_id = booking.get("vehicle_id")
        if not vehicle_id:
            continue
        vehicle = await _fetch_vehicle(UUID(str(vehicle_id)))
        vehicle_type = vehicle.get("type")
        if vehicle_type:
            vehicle_types.append(str(vehicle_type))

    preferred_vehicle_type = Counter(vehicle_types).most_common(1)[0][0] if vehicle_types else None
    spends = [float(booking.get("total_price", 0)) for booking in bookings if booking.get("total_price") is not None]
    average_spend = round(mean(spends), 2) if spends else 0.0
    loyalty_points = int(customer.get("loyalty_points", 0) or 0)

    summary = CustomerPreferences(
        customer_id=customer_uuid,
        preferred_vehicle_type=preferred_vehicle_type,
        average_spend=average_spend,
        loyalty_points=loyalty_points,
        total_bookings=len(bookings),
    )
    return summary.model_dump_json()


async def recommend_vehicles(customer_id: str, dates: dict[str, str]) -> str:
    """Recommend and rank available vehicles by customer preference match."""
    customer_uuid = UUID(customer_id)
    date_range = RecommendationDates.model_validate(dates)
    preferences_json = await get_customer_preferences(str(customer_uuid))
    preferences = CustomerPreferences.model_validate_json(preferences_json)

    preferred_type = preferences.preferred_vehicle_type
    vehicles = await _fetch_available_vehicles(preferred_type)
    if not vehicles:
        vehicles = await _fetch_available_vehicles()

    ranked: list[dict[str, Any]] = []
    for vehicle in vehicles:
        score = 0.0
        if preferred_type and vehicle.get("type") == preferred_type:
            score += 60.0

        price_per_day = float(vehicle.get("price_per_day", 0) or 0)
        if preferences.average_spend > 0:
            relative_diff = abs(price_per_day - preferences.average_spend) / preferences.average_spend
            score += max(0.0, 30.0 * (1.0 - relative_diff))
        else:
            score += 15.0

        if preferences.loyalty_points >= 100:
            score += 10.0

        ranked.append(
            {
                "vehicle_id": vehicle.get("id"),
                "type": vehicle.get("type"),
                "brand": vehicle.get("brand"),
                "model": vehicle.get("model"),
                "location": vehicle.get("location"),
                "price_per_day": vehicle.get("price_per_day"),
                "match_score": round(score, 2),
                "pickup_date": date_range.pickup_date.isoformat(),
                "return_date": date_range.return_date.isoformat(),
            }
        )

    ranked.sort(key=lambda item: item["match_score"], reverse=True)
    return json.dumps(
        {
            "customer_id": str(customer_uuid),
            "recommended_vehicles": ranked[:5],
        }
    )
