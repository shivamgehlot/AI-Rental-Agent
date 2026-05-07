"""Celery beat task for RideSwift no-show auto-cancellations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import httpx
from celery import Celery
from pydantic_settings import BaseSettings, SettingsConfigDict
from twilio.rest import Client as TwilioClient


class NoShowSettings(BaseSettings):
    """Runtime settings for no-show handling workflow."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    CELERY_BROKER_URL: str = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/1"
    BACKEND_API_URL: str = "http://backend:8000"
    BACKEND_API_TOKEN: str | None = None
    SLACK_BOT_TOKEN: str
    SLACK_CHANNEL: str = "#pickup-managers"
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_FROM_PHONE: str


@lru_cache(maxsize=1)
def get_settings() -> NoShowSettings:
    """Return cached configuration settings."""
    return NoShowSettings()


settings = get_settings()
celery_app = Celery(
    "rideswift_no_show_handler",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.beat_schedule = {
    "cancel-no-show-bookings-every-30-minutes": {
        "task": "slack-bot.no_show_handler.cancel_no_show_bookings",
        "schedule": timedelta(minutes=30),
    }
}
celery_app.conf.timezone = "UTC"


def _backend_headers() -> dict[str, str]:
    """Build backend auth headers for service requests."""
    if settings.BACKEND_API_TOKEN:
        return {"Authorization": f"Bearer {settings.BACKEND_API_TOKEN}"}
    return {}


async def _post_slack_message(booking_id: str) -> None:
    """Send no-show cancellation alert to pickup managers channel."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "channel": settings.SLACK_CHANNEL,
                "text": f"Auto-cancelled no-show: Booking {booking_id}",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok", False):
            raise httpx.HTTPStatusError(
                "Slack API rejected message",
                request=response.request,
                response=response,
            )


def _send_sms(phone_number: str, booking_id: str) -> None:
    """Send no-show cancellation SMS via Twilio."""
    twilio_client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    twilio_client.messages.create(
        body=f"Your RideSwift booking {booking_id} was auto-cancelled due to no-show at pickup.",
        from_=settings.TWILIO_FROM_PHONE,
        to=phone_number,
    )


async def _fetch_pending_no_shows(cutoff_iso: str) -> list[dict[str, Any]]:
    """Fetch pending bookings whose pickup time passed the no-show threshold."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/bookings",
            params={"status": "pending", "pickup_to": cutoff_iso},
            headers=_backend_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        return []


async def _cancel_booking(booking_id: str) -> None:
    """Cancel booking by marking status as cancelled via backend API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.patch(
            f"{settings.BACKEND_API_URL}/bookings/{booking_id}",
            json={"status": "cancelled"},
            headers=_backend_headers(),
        )
        response.raise_for_status()


async def _fetch_customer_phone(customer_id: str) -> str | None:
    """Fetch customer phone number from backend."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/customers/{customer_id}",
            headers=_backend_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        phone = payload.get("phone") if isinstance(payload, dict) else None
        return str(phone) if phone else None


async def process_no_shows() -> int:
    """Run one no-show processing pass and return cancelled count."""
    cutoff = datetime.now(UTC) - timedelta(hours=2)
    cutoff_iso = cutoff.isoformat()
    bookings = await _fetch_pending_no_shows(cutoff_iso)
    cancelled_count = 0

    for booking in bookings:
        booking_id = str(booking.get("id", ""))
        customer_id = str(booking.get("customer_id", ""))
        pickup_date = booking.get("pickup_date")
        if not booking_id or not customer_id or not pickup_date:
            continue
        pickup_dt = datetime.fromisoformat(str(pickup_date).replace("Z", "+00:00"))
        if pickup_dt > cutoff:
            continue

        await _cancel_booking(booking_id)
        await _post_slack_message(booking_id)
        phone_number = await _fetch_customer_phone(customer_id)
        if phone_number:
            await asyncio.to_thread(_send_sms, phone_number, booking_id)
        cancelled_count += 1

    return cancelled_count


@celery_app.task(name="slack-bot.no_show_handler.cancel_no_show_bookings")
def cancel_no_show_bookings() -> dict[str, int]:
    """Celery task entrypoint that auto-cancels no-show bookings."""
    cancelled = asyncio.run(process_no_shows())
    return {"cancelled": cancelled}
