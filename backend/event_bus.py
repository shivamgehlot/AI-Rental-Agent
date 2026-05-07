"""Kafka event publisher utilities."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from kafka import KafkaProducer
from kafka.errors import KafkaError
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class EventSettings(BaseSettings):
    """Settings for Kafka event publishing."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"


@lru_cache(maxsize=1)
def get_event_settings() -> EventSettings:
    """Return cached event settings."""
    return EventSettings()


@lru_cache(maxsize=1)
def get_kafka_producer() -> KafkaProducer:
    """Build a shared Kafka producer."""
    settings = get_event_settings()
    return KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda payload: json.dumps(payload, default=str).encode("utf-8"),
    )


def publish_event(topic: str, payload: dict[str, Any]) -> None:
    """Publish a Kafka event and raise if delivery fails."""
    producer = get_kafka_producer()
    try:
        future = producer.send(topic, payload)
        future.get(timeout=5)
    except KafkaError as exc:
        logger.exception("Kafka publish failed for topic=%s", topic)
        raise RuntimeError("Failed to publish Kafka event") from exc
