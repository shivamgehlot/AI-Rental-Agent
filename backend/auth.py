"""Authentication and authorization for RideSwift backend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Customer
from schemas import CustomerCreate, CustomerResponse, LoginRequest, TokenResponse

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthSettings(BaseSettings):
    """Auth settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    SECRET_KEY: str = "rideswift-super-secret-key-change-in-prod"


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return cached auth settings."""
    return AuthSettings()


def hash_password(plain: str) -> str:
    """Hash plaintext password using bcrypt."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify plaintext password against stored hash."""
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    """Create access JWT with 30-minute expiry."""
    settings = get_auth_settings()
    to_encode = data.copy()
    to_encode.update(
        {
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        }
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create refresh JWT with 7-day expiry."""
    settings = get_auth_settings()
    to_encode = data.copy()
    to_encode.update(
        {
            "type": "refresh",
            "exp": datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        }
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and validate JWT payload."""
    settings = get_auth_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
    return payload


async def get_current_customer(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Customer:
    """Resolve currently authenticated customer from bearer token."""
    payload = verify_token(token)
    subject = payload.get("sub")
    token_type = payload.get("type")
    if not subject or token_type != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        customer_id = UUID(subject)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject") from exc

    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Customer not found")
    return customer


# Backward-compatible dependency name used by existing routers.
get_current_user = get_current_customer


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: CustomerCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Create customer account and return access/refresh tokens."""
    existing = await db.execute(select(Customer).where(Customer.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    customer = Customer(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
    )
    db.add(customer)
    try:
        await db.flush()
        await db.refresh(customer)
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to register") from exc

    subject = {"sub": str(customer.id)}
    return TokenResponse(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
        token_type="bearer",
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate customer and issue JWT tokens."""
    result = await db.execute(select(Customer).where(Customer.email == payload.email))
    customer = result.scalar_one_or_none()
    if customer is None or not verify_password(payload.password, customer.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    subject = {"sub": str(customer.id)}
    return TokenResponse(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
        token_type="bearer",
    )


@router.get("/me", response_model=CustomerResponse)
async def me(current_customer: Annotated[Customer, Depends(get_current_customer)]) -> Customer:
    """Return current authenticated customer profile."""
    return current_customer
