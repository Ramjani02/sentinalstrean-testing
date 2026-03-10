"""
SentinelStream - Async Database Engine & Session Management
Uses SQLAlchemy 2.0 with asyncpg for non-blocking database access.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# ── Engine ──────────────────────────────────────────────────────
# pool_pre_ping: automatically reconnects stale connections
# pool_size / max_overflow: tuned for high-concurrency production workload
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_timeout=30,
    pool_recycle=1800,
)

# ── Session Factory ─────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── Base Model ───────────────────────────────────────────────────
class Base(DeclarativeBase):
    """
    Declarative base class for all SQLAlchemy ORM models.
    All models must inherit from this class.
    """
    pass


# ── Dependency ───────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an async database session.
    Automatically commits on success, rolls back on exception,
    and always closes the session.

    Usage:
        @router.post("/")
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
