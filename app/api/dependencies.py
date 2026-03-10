"""
SentinelStream - FastAPI Dependencies
Reusable dependency functions for authentication, database access,
and service injection.
"""

import uuid
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_token
from app.db.session import get_db
from app.models.models import User, UserRole

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency: Decode the JWT and return the authenticated User object.
    Raises HTTP 401 if the token is missing, expired, or invalid.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise credentials_exception

    result = await db.execute(
        select(User).where(
            User.id == uuid.UUID(user_id),
            User.is_active == True,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency: Ensures the authenticated user account is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Dependency: Restrict endpoint access to ADMIN role only."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


async def require_analyst_or_above(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Dependency: Allow ADMIN and ANALYST roles."""
    allowed = {UserRole.ADMIN, UserRole.ANALYST}
    if current_user.role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analyst or Admin privileges required",
        )
    return current_user
