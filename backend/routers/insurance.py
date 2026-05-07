"""Insurance API routes."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from auth import get_current_user
from event_bus import publish_event

router = APIRouter(prefix="/insurance", tags=["insurance"], dependencies=[Depends(get_current_user)])


class InsuranceSettings(BaseSettings):
    """Settings for insurance service integration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    RAG_SERVICE_URL: str = "http://rag-service:8002"


@lru_cache(maxsize=1)
def get_insurance_settings() -> InsuranceSettings:
    """Return cached settings object."""
    return InsuranceSettings()


class InsuranceQueryRequest(BaseModel):
    """Insurance query request payload."""

    question: str = Field(min_length=1)


@router.post("/upload/{customer_id}")
async def upload_insurance(
    customer_id: UUID,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Proxy insurance upload to RAG service."""
    settings = get_insurance_settings()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.RAG_SERVICE_URL}/rag/upload/{customer_id}",
                files={"file": (file.filename, await file.read(), file.content_type or "application/pdf")},
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="RAG service request failed") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG service unavailable",
        ) from exc

    try:
        publish_event(
            "insurance.uploaded",
            {
                "customer_id": str(customer_id),
                "file_name": file.filename,
            },
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event stream unavailable",
        ) from exc

    return result


@router.post("/query/{customer_id}")
async def query_insurance(
    customer_id: UUID,
    payload: InsuranceQueryRequest,
) -> dict[str, Any]:
    """Proxy insurance query to RAG service."""
    settings = get_insurance_settings()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.RAG_SERVICE_URL}/rag/query/{customer_id}",
                json={"question": payload.question},
            )
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="RAG service request failed") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG service unavailable",
        ) from exc
    return result
