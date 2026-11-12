"""Authentication endpoints.

Registration and login are rate-limited separately from search, because they are
the endpoints an attacker actually hammers. Login failures return the same
message whether the email exists or not — no account enumeration.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.config import settings
from app.models import User
from app.rate_limit import limiter
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security import CurrentUser, DbSession, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: DbSession,
) -> TokenResponse:
    limiter.check(request, "auth", settings.rate_limit_auth_per_minute)

    email = payload.email.lower().strip()
    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )

    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    user = User(
        email=email,
        display_name=payload.display_name,
        password_hash=password_hash,
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse, summary="Sign in")
async def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenResponse:
    limiter.check(request, "auth", settings.rate_limit_auth_per_minute)

    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))

    # Same error for "no such user" and "wrong password".
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled"
        )

    user.last_login_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.get("/me", response_model=UserOut, summary="Current user")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
