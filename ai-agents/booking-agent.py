"""RideSwift booking agent service with personalization-aware tools."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from langchain.agents import AgentType, initialize_agent
from langchain_community.chat_models import ChatOllama
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.tools import StructuredTool
from pydantic_settings import BaseSettings, SettingsConfigDict

from personalization import get_customer_preferences, recommend_vehicles


class AgentSettings(BaseSettings):
    """Runtime settings for booking agent integrations."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    BACKEND_API_URL: str = "http://backend:8000"
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "mistral"
    BACKEND_API_TOKEN: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> AgentSettings:
    """Return cached settings."""
    return AgentSettings()


def _headers() -> dict[str, str]:
    """Build backend auth headers if token is configured."""
    settings = get_settings()
    if settings.BACKEND_API_TOKEN:
        return {"Authorization": f"Bearer {settings.BACKEND_API_TOKEN}"}
    return {}


class AvailabilityInput(BaseModel):
    """Input for availability checks."""

    vehicle_type: str | None = Field(default=None)
    location: str | None = Field(default=None)


class CreateBookingInput(BaseModel):
    """Input for booking creation."""

    customer_id: str
    vehicle_id: str
    pickup_date: str
    return_date: str
    total_price: float
    notes: str | None = None


class ModifyBookingInput(BaseModel):
    """Input for booking updates."""

    booking_id: str
    pickup_date: str | None = None
    return_date: str | None = None
    total_price: float | None = None
    status: str | None = None
    notes: str | None = None


class PreferencesInput(BaseModel):
    """Input for customer preference lookup."""

    customer_id: str


class RecommendationsInput(BaseModel):
    """Input for personalized recommendations."""

    customer_id: str
    dates: dict[str, str]


async def check_availability(vehicle_type: str | None = None, location: str | None = None) -> str:
    """Fetch available vehicles with optional filters."""
    settings = get_settings()
    params: dict[str, str] = {"status": "available"}
    if vehicle_type:
        params["type"] = vehicle_type
    if location:
        params["location"] = location

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{settings.BACKEND_API_URL}/vehicles",
            params=params,
            headers=_headers(),
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch inventory")
    return json.dumps(response.json())


async def create_booking(
    customer_id: str,
    vehicle_id: str,
    pickup_date: str,
    return_date: str,
    total_price: float,
    notes: str | None = None,
) -> str:
    """Create a booking in backend."""
    settings = get_settings()
    payload: dict[str, Any] = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "pickup_date": pickup_date,
        "return_date": return_date,
        "total_price": total_price,
        "notes": notes,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{settings.BACKEND_API_URL}/bookings",
            json=payload,
            headers=_headers(),
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail="Failed to create booking")
    return json.dumps(response.json())


async def modify_booking(
    booking_id: str,
    pickup_date: str | None = None,
    return_date: str | None = None,
    total_price: float | None = None,
    status: str | None = None,
    notes: str | None = None,
) -> str:
    """Modify a booking in backend."""
    settings = get_settings()
    payload = {
        key: value
        for key, value in {
            "pickup_date": pickup_date,
            "return_date": return_date,
            "total_price": total_price,
            "status": status,
            "notes": notes,
        }.items()
        if value is not None
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.patch(
            f"{settings.BACKEND_API_URL}/bookings/{booking_id}",
            json=payload,
            headers=_headers(),
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail="Failed to modify booking")
    return json.dumps(response.json())


tools = [
    StructuredTool.from_function(
        coroutine=check_availability,
        name="check_availability",
        description="Check available vehicles with optional type/location filters.",
        args_schema=AvailabilityInput,
    ),
    StructuredTool.from_function(
        coroutine=create_booking,
        name="create_booking",
        description="Create a new vehicle booking.",
        args_schema=CreateBookingInput,
    ),
    StructuredTool.from_function(
        coroutine=modify_booking,
        name="modify_booking",
        description="Modify an existing booking.",
        args_schema=ModifyBookingInput,
    ),
    StructuredTool.from_function(
        coroutine=get_customer_preferences,
        name="get_customer_preferences",
        description=(
            "Fetch booking history insights for a returning customer and return "
            "preferred vehicle type, average spend, and loyalty points."
        ),
        args_schema=PreferencesInput,
    ),
    StructuredTool.from_function(
        coroutine=recommend_vehicles,
        name="recommend_vehicles",
        description="Recommend and rank available vehicles for customer and dates.",
        args_schema=RecommendationsInput,
    ),
]

settings = get_settings()
llm = ChatOllama(model=settings.OLLAMA_MODEL, base_url=settings.OLLAMA_BASE_URL, temperature=0)
agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    agent_kwargs={
        "system_message": (
            "You are RideSwift's booking assistant. "
            "Always call get_customer_preferences first for returning customers "
            "before proposing or booking vehicles."
        )
    },
)

app = FastAPI(title="RideSwift Booking Agent")


class AgentQueryRequest(BaseModel):
    """Incoming query payload for agent execution."""

    message: str = Field(min_length=1)


@app.post("/agent/query")
async def agent_query(payload: AgentQueryRequest) -> dict[str, Any]:
    """Run booking agent on incoming prompt."""
    result = await agent.ainvoke({"input": payload.message})
    return {"result": result.get("output", result)}
