"""Standalone async Kafka consumer for RideSwift booking lifecycle events."""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from decimal import Decimal
from email.message import EmailMessage
from functools import lru_cache
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from kafka import KafkaConsumer
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import Booking, Customer, Vehicle

logger = logging.getLogger("rideswift.kafka_consumer")
logging.basicConfig(level=logging.INFO)


class ConsumerSettings(BaseSettings):
    """Runtime configuration for consumer integrations."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    REDIS_URL: str = "redis://redis:6379"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@rideswift.local"


@lru_cache(maxsize=1)
def get_settings() -> ConsumerSettings:
    """Return cached settings instance."""
    return ConsumerSettings()


def _build_consumer(settings: ConsumerSettings) -> KafkaConsumer:
    """Create Kafka consumer subscribed to required booking topics."""
    return KafkaConsumer(
        "booking.created",
        "booking.confirmed",
        "booking.cancelled",
        "booking.completed",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        consumer_timeout_ms=1000,
    )


async def _publish_inventory_update(redis_client: aioredis.Redis, payload: dict[str, Any]) -> None:
    """Publish inventory update payload to Redis channel."""
    await redis_client.publish("inventory:updates", json.dumps(payload, default=str))


def _send_confirmation_email(
    settings: ConsumerSettings,
    to_email: str,
    booking: Booking,
    vehicle: Vehicle,
) -> None:
    """Send booking confirmation email via SMTP."""
    if not settings.SMTP_USER or not settings.SMTP_PASS:
        logger.warning("SMTP credentials missing. Skipping email for booking %s", booking.id)
        return

    message = EmailMessage()
    message["Subject"] = "RideSwift — Booking Confirmed 🚗"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(
        "Your booking is confirmed.\n\n"
        f"Booking ID: {booking.id}\n"
        f"Vehicle: {vehicle.brand} {vehicle.model_name} ({vehicle.plate})\n"
        f"Pickup: {booking.pickup_date.isoformat()}\n"
        f"Return: {booking.return_date.isoformat()}\n"
        f"Amount: {booking.total_amount}\n\n"
        "Pickup instructions:\n"
        "1. Bring your driving license and booking ID.\n"
        "2. Arrive 15 minutes early at your pickup location.\n"
        "3. Contact support if your arrival is delayed."
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
        smtp.send_message(message)


async def _get_booking(db: AsyncSession, booking_id: UUID) -> Booking | None:
    """Fetch booking by id."""
    result = await db.execute(select(Booking).where(Booking.id == booking_id))
    return result.scalar_one_or_none()


async def _get_vehicle(db: AsyncSession, vehicle_id: UUID) -> Vehicle | None:
    """Fetch vehicle by id."""
    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    return result.scalar_one_or_none()


async def _get_customer(db: AsyncSession, customer_id: UUID) -> Customer | None:
    """Fetch customer by id."""
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    return result.scalar_one_or_none()


async def _handle_booking_created(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    settings: ConsumerSettings,
    payload: dict[str, Any],
) -> None:
    """Handle booking.created lifecycle action."""
    booking_id = UUID(str(payload["booking_id"]))
    booking = await _get_booking(db, booking_id)
    if booking is None:
        logger.warning("booking.created received for unknown booking %s", booking_id)
        return

    vehicle = await _get_vehicle(db, booking.vehicle_id)
    customer = await _get_customer(db, booking.customer_id)
    if vehicle is None or customer is None:
        logger.warning("booking.created missing vehicle/customer for booking %s", booking_id)
        return

    logger.info("booking.created event processed: %s", booking_id)
    await _publish_inventory_update(
        redis_client,
        {
            "type": "new_booking",
            "vehicle_id": str(vehicle.id),
            "message": f"Vehicle {vehicle.plate} booked until {booking.return_date.isoformat()}",
        },
    )
    _send_confirmation_email(settings, customer.email, booking, vehicle)


async def _handle_booking_confirmed(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    payload: dict[str, Any],
) -> None:
    """Handle booking.confirmed lifecycle action."""
    booking_id = UUID(str(payload["booking_id"]))
    booking = await _get_booking(db, booking_id)
    if booking is None:
        logger.warning("booking.confirmed received for unknown booking %s", booking_id)
        return

    booking.status = "confirmed"
    await db.flush()
    await db.commit()
    await _publish_inventory_update(
        redis_client,
        {
            "type": "booking_confirmed",
            "booking_id": str(booking.id),
            "vehicle_id": str(booking.vehicle_id),
            "message": f"Booking {booking.id} confirmed",
        },
    )


async def _handle_booking_cancelled(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    payload: dict[str, Any],
) -> None:
    """Handle booking.cancelled lifecycle action."""
    booking_id = UUID(str(payload["booking_id"]))
    booking = await _get_booking(db, booking_id)
    if booking is None:
        logger.warning("booking.cancelled received for unknown booking %s", booking_id)
        return

    vehicle = await _get_vehicle(db, booking.vehicle_id)
    if vehicle is None:
        logger.warning("booking.cancelled missing vehicle for booking %s", booking_id)
        return

    vehicle.status = "available"
    await db.flush()
    await db.commit()
    await _publish_inventory_update(
        redis_client,
        {
            "type": "vehicle_available",
            "vehicle_id": str(vehicle.id),
            "message": f"Vehicle {vehicle.plate} now available",
        },
    )


async def _handle_booking_completed(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    payload: dict[str, Any],
) -> None:
    """Handle booking.completed lifecycle action."""
    booking_id = UUID(str(payload["booking_id"]))
    booking = await _get_booking(db, booking_id)
    if booking is None:
        logger.warning("booking.completed received for unknown booking %s", booking_id)
        return

    vehicle = await _get_vehicle(db, booking.vehicle_id)
    customer = await _get_customer(db, booking.customer_id)
    if vehicle is None or customer is None:
        logger.warning("booking.completed missing vehicle/customer for booking %s", booking_id)
        return

    vehicle.status = "available"
    loyalty_points_to_add = int(Decimal(str(booking.total_amount)))
    customer.loyalty_points = int(customer.loyalty_points or 0) + loyalty_points_to_add
    await db.flush()
    await db.commit()

    await _publish_inventory_update(
        redis_client,
        {
            "type": "booking_completed",
            "booking_id": str(booking.id),
            "vehicle_id": str(vehicle.id),
            "message": f"Vehicle {vehicle.plate} returned and now available",
        },
    )


async def process_event(
    topic: str,
    payload: dict[str, Any],
    redis_client: aioredis.Redis,
    settings: ConsumerSettings,
) -> None:
    """Process a single consumed Kafka event."""
    async with AsyncSessionLocal() as db:
        try:
            if topic == "booking.created":
                await _handle_booking_created(db, redis_client, settings, payload)
            elif topic == "booking.confirmed":
                await _handle_booking_confirmed(db, redis_client, payload)
            elif topic == "booking.cancelled":
                await _handle_booking_cancelled(db, redis_client, payload)
            elif topic == "booking.completed":
                await _handle_booking_completed(db, redis_client, payload)
        except KeyError as exc:
            await db.rollback()
            logger.error("Malformed payload for topic %s: missing %s", topic, exc)
        except ValueError as exc:
            await db.rollback()
            logger.error("Invalid payload format for topic %s: %s", topic, exc)
        except SQLAlchemyError:
            await db.rollback()
            logger.exception("Database operation failed while processing topic %s", topic)
        except smtplib.SMTPException:
            await db.rollback()
            logger.exception("SMTP send failed while processing booking.created")


async def consume_events() -> None:
    """Start polling Kafka and route events to handlers."""
    settings = get_settings()
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    consumer = _build_consumer(settings)
    logger.info("RideSwift Kafka consumer started")

    try:
        while True:
            records = await asyncio.to_thread(consumer.poll, 1.0)
            for _, batch in records.items():
                for message in batch:
                    if not isinstance(message.value, dict):
                        logger.warning("Skipping non-dict message on topic %s", message.topic)
                        continue
                    await process_event(message.topic, message.value, redis_client, settings)
            await asyncio.sleep(0)
    finally:
        consumer.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(consume_events())
