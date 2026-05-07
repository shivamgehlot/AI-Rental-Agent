"""Prometheus metrics setup for RideSwift backend."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Vehicle

bookings_created_total = Counter(
    "bookings_created_total",
    "Total number of bookings created.",
)

active_vehicles_count = Gauge(
    "active_vehicles_count",
    "Current count of available vehicles.",
)

api_response_time_seconds = Histogram(
    "api_response_time_seconds",
    "API response time in seconds.",
    ["method", "path", "status_code"],
)

agent_query_latency_seconds = Histogram(
    "agent_query_latency_seconds",
    "Latency of agent-related API routes.",
)


def record_booking_created() -> None:
    """Increment booking creation counter."""
    bookings_created_total.inc()


async def refresh_active_vehicles_count(db: AsyncSession) -> None:
    """Recalculate active vehicle count metric."""
    result = await db.execute(select(Vehicle.id).where(Vehicle.status == "available"))
    active_vehicles_count.set(len(result.scalars().all()))


def setup_metrics(app: FastAPI) -> None:
    """Attach middleware and expose /metrics endpoint."""
    instrumentator = Instrumentator()
    instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    @app.middleware("http")
    async def observe_request_latency(request: Request, call_next):  # type: ignore[no-redef]
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        path = request.url.path
        method = request.method
        status_code = str(response.status_code)

        api_response_time_seconds.labels(
            method=method,
            path=path,
            status_code=status_code,
        ).observe(duration)
        if path.startswith("/agent"):
            agent_query_latency_seconds.observe(duration)
        return response
