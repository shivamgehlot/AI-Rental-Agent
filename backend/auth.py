"""Authentication and authorization utilities for RideSwift."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Customer
from schemas import CustomerResponse

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=True)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthSettings(BaseSettings):
    """JWT and auth configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    JWT_SECRET_KEY: str = "dev_access_secret_change_me"
    JWT_REFRESH_SECRET_KEY: str = "dev_refresh_secret_change_me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 43200


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return cached auth settings."""
    return AuthSettings()


class RegisterRequest(BaseModel):
    """Incoming register request body."""

    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    """Incoming login request body."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    """Auth token response payload."""

    model_config = ConfigDict(from_attributes=True)
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def get_password_hash(password: str) -> str:
    """Hash a plaintext password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify plaintext password against its hash."""
    return pwd_context.verify(plain_password, password_hash)


def _create_token(
    customer_id: UUID,
    secret_key: str,
    algorithm: str,
    expires_minutes: int,
    token_type: str,
) -> str:
    """Create a signed JWT."""
    expires_at = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    payload = {"sub": str(customer_id), "exp": expires_at, "type": token_type}
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def create_access_token(customer_id: UUID) -> str:
    """Create an access token."""
    settings = get_auth_settings()
    return _create_token(
        customer_id=customer_id,
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        token_type="access",
    )


def create_refresh_token(customer_id: UUID) -> str:
    """Create a refresh token."""
    settings = get_auth_settings()
    return _create_token(
        customer_id=customer_id,
        secret_key=settings.JWT_REFRESH_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES,
        token_type="refresh",
    )


@router.post("/register", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def register_customer(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Customer:
    """Register a new customer account with hashed password."""
    existing_customer_result = await db.execute(select(Customer).where(Customer.email == payload.email))
    existing_customer = existing_customer_result.scalar_one_or_none()
    if existing_customer is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Customer with this email already exists",
        )

    customer = Customer(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password_hash=get_password_hash(payload.password),
    )
    db.add(customer)
    try:
        await db.commit()
        await db.refresh(customer)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Customer with this email already exists",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register customer",
        ) from exc
    return customer


@router.post("/login", response_model=TokenResponse)
async def login_customer(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate a customer and issue tokens."""
    result = await db.execute(select(Customer).where(Customer.email == payload.email))
    customer = result.scalar_one_or_none()
    if customer is None or customer.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_password(payload.password, customer.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return TokenResponse(
        access_token=create_access_token(customer.id),
        refresh_token=create_refresh_token(customer.id),
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Customer:
    """Decode bearer token and return the authenticated customer."""
    settings = get_auth_settings()
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        token_type = payload.get("type")
        subject = payload.get("sub")
        if token_type != "access" or not subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        customer_id = UUID(subject)
    except (JWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc

    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return customer
