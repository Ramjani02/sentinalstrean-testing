"""
SentinelStream - Authentication Endpoints
POST /auth/register  - Create a new user account
POST /auth/login     - Obtain JWT access + refresh tokens
POST /auth/refresh   - Exchange refresh token for new access token
GET  /auth/me        - Get current authenticated user profile
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.models import Account, User, UserRole
from app.schemas.schemas import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(
    request: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Create a new user account with hashed password.
    Automatically provisions a default checking account.
    """
    # Check for duplicate email
    result = await db.execute(
        select(User).where(User.email == request.email.lower())
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        id=uuid.uuid4(),
        email=request.email.lower(),
        hashed_password=get_password_hash(request.password),
        full_name=request.full_name,
        role=UserRole.VIEWER,
        home_country=request.home_country,
        home_city=request.home_city,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.flush()  # Get the user.id before creating the account

    # Auto-provision a checking account
    account_number = f"SS{str(user.id).replace('-', '')[:16].upper()}"
    account = Account(
        id=uuid.uuid4(),
        user_id=user.id,
        account_number=account_number,
        account_type="checking",
        balance=10_000.00,  # Demo seed balance
        currency="USD",
        is_active=True,
    )
    db.add(account)
    await db.commit()
    await db.refresh(user)

    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive JWT tokens",
)
async def login(
    request: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Validate credentials and return an access token + refresh token.
    The access token expires after `ACCESS_TOKEN_EXPIRE_MINUTES`.
    """
    result = await db.execute(
        select(User).where(User.email == request.email.lower(), User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login timestamp
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Exchange a valid refresh token for a new access token pair.
    """
    user_id = verify_token(refresh_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id), User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse.model_validate(current_user)
