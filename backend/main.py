"""RideSwift FastAPI application entrypoint."""

from __future__ import annotations

from functools import lru_cache

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings, SettingsConfigDict

from auth import router as auth_router
from metrics import setup_metrics
from routers.bookings import router as bookings_router
from routers.customers import router as customers_router
from routers.insurance import router as insurance_router
from routers.vehicles import router as vehicles_router


class ApiSettings(BaseSettings):
    """Runtime API settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    REDIS_URL: str = "redis://redis:6379"


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    """Return cached API settings."""
    return ApiSettings()


settings = get_api_settings()
redis_client = aioredis.from_url(settings.REDIS_URL)

app = FastAPI(title="RideSwift API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
setup_metrics(app)

app.include_router(vehicles_router)
app.include_router(customers_router)
app.include_router(auth_router)
app.include_router(bookings_router)
app.include_router(insurance_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple healthcheck endpoint."""
    return {"status": "ok"}


@app.websocket("/ws/inventory")
async def inventory_ws(websocket: WebSocket) -> None:
    """Stream inventory updates from Redis pub/sub."""
    await websocket.accept()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("inventory:updates")
    async for message in pubsub.listen():
        if message["type"] == "message":
            data = message["data"]
            payload = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data)
            await websocket.send_text(payload)
