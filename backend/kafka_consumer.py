"""Standalone async Kafka consumer for booking lifecycle events."""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
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

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ConsumerSettings(BaseSettings):
    """Runtime configuration for the Kafka consumer process."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    REDIS_URL: str = "redis://redis:6379"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_FROM_EMAIL: str
    SMTP_USE_TLS: bool = True


@lru_cache(maxsize=1)
def get_settings() -> ConsumerSettings:
    """Return cached consumer settings."""
    return ConsumerSettings()


def _build_consumer(settings: ConsumerSettings) -> KafkaConsumer:
    """Create Kafka consumer subscribed to booking topics."""
    return KafkaConsumer(
        "booking.created",
        "booking.cancelled",
        "booking.confirmed",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        consumer_timeout_ms=1000,
    )


async def _publish_inventory_update(
    redis_client: aioredis.Redis,
    vehicle_id: UUID,
    status_value: str,
) -> None:
    """Publish vehicle state changes to Redis inventory channel."""
    payload = json.dumps({"vehicle_id": str(vehicle_id), "status": status_value})
    await redis_client.publish("inventory:updates", payload)


async def _update_vehicle_status(
    db: AsyncSession,
    booking: Booking,
    next_status: str,
) -> None:
    """Update booking vehicle status in database."""
    vehicle = await db.get(Vehicle, booking.vehicle_id)
    if vehicle is None:
        logger.warning("Vehicle %s not found for booking %s", booking.vehicle_id, booking.id)
        return
    vehicle.status = next_status


def _send_confirmation_email(
    settings: ConsumerSettings,
    to_email: str,
    booking_id: UUID,
) -> None:
    """Send booking confirmation email using SMTP."""
    message = EmailMessage()
    message["Subject"] = "RideSwift Booking Confirmed"
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message.set_content(
        f"Your booking {booking_id} has been confirmed.\n"
        "Thank you for choosing RideSwift."
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)


async def _handle_booking_created(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    payload: dict[str, Any],
) -> None:
    """Handle booking.created by marking vehicle as rented and publishing updates."""
    booking_id = payload.get("booking_id")
    if booking_id is None:
        logger.warning("booking.created missing booking_id")
        return

    booking = await db.get(Booking, UUID(str(booking_id)))
    if booking is None:
        logger.warning("Booking %s not found", booking_id)
        return

    await _update_vehicle_status(db, booking, "rented")
    await db.commit()
    await _publish_inventory_update(redis_client, booking.vehicle_id, "rented")
    logger.info("Processed booking.created for %s", booking_id)


async def _handle_booking_cancelled(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    payload: dict[str, Any],
) -> None:
    """Handle booking.cancelled by marking vehicle as available and publishing updates."""
    booking_id = payload.get("booking_id")
    if booking_id is None:
        logger.warning("booking.cancelled missing booking_id")
        return

    booking = await db.get(Booking, UUID(str(booking_id)))
    if booking is None:
        logger.warning("Booking %s not found", booking_id)
        return

    await _update_vehicle_status(db, booking, "available")
    await db.commit()
    await _publish_inventory_update(redis_client, booking.vehicle_id, "available")
    logger.info("Processed booking.cancelled for %s", booking_id)


async def _handle_booking_confirmed(
    db: AsyncSession,
    settings: ConsumerSettings,
    payload: dict[str, Any],
) -> None:
    """Handle booking.confirmed by sending confirmation email."""
    booking_id = payload.get("booking_id")
    if booking_id is None:
        logger.warning("booking.confirmed missing booking_id")
        return

    booking = await db.get(Booking, UUID(str(booking_id)))
    if booking is None:
        logger.warning("Booking %s not found", booking_id)
        return

    customer_result = await db.execute(select(Customer).where(Customer.id == booking.customer_id))
    customer = customer_result.scalar_one_or_none()
    if customer is None:
        logger.warning("Customer %s not found for booking %s", booking.customer_id, booking.id)
        return

    _send_confirmation_email(settings, customer.email, booking.id)
    logger.info("Processed booking.confirmed for %s", booking_id)


async def process_event(
    topic: str,
    payload: dict[str, Any],
    redis_client: aioredis.Redis,
    settings: ConsumerSettings,
) -> None:
    """Route each consumed event to its handler."""
    async with AsyncSessionLocal() as db:
        try:
            if topic == "booking.created":
                await _handle_booking_created(db, redis_client, payload)
            elif topic == "booking.cancelled":
                await _handle_booking_cancelled(db, redis_client, payload)
            elif topic == "booking.confirmed":
                await _handle_booking_confirmed(db, settings, payload)
        except ValueError:
            await db.rollback()
            logger.exception("Invalid payload for topic %s", topic)
        except smtplib.SMTPException:
            await db.rollback()
            logger.exception("Failed sending email for booking.confirmed")
        except SQLAlchemyError:
            await db.rollback()
            logger.exception("Failed processing topic %s", topic)


async def consume_events() -> None:
    """Run the consumer loop and process events asynchronously."""
    settings = get_settings()
    redis_client = aioredis.from_url(settings.REDIS_URL)
    consumer = _build_consumer(settings)
    logger.info("Kafka consumer started")

    try:
        while True:
            records = await asyncio.to_thread(consumer.poll, 1.0)
            for _, batch in records.items():
                for message in batch:
                    if not isinstance(message.value, dict):
                        logger.warning("Ignoring non-dict payload on topic %s", message.topic)
                        continue
                    await process_event(message.topic, message.value, redis_client, settings)
            await asyncio.sleep(0)
    finally:
        consumer.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(consume_events())
