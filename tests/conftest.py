"""
SentinelStream - PyTest Configuration & Shared Fixtures

Provides a complete isolated test environment:
  - In-memory SQLite database (no external PostgreSQL needed)
  - Mocked Redis
  - Authenticated test client
  - Pre-seeded test data (users, accounts, merchants)
"""

import asyncio
import uuid
from decimal import Decimal
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, get_password_hash
from app.db.session import Base, get_db
from app.models.models import Account, Merchant, User, UserRole
from app.main import create_application

# ── Test Database (SQLite in-memory) ─────────────────────────────
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a session-scoped async SQLite engine."""
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh transactional test session that is rolled back after each test."""
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def mock_redis():
    """Mock Redis client - avoids needing a real Redis server in unit tests."""
    redis = AsyncMock()
    redis.ping.return_value = True
    redis.get.return_value = None          # Default: no cache hit
    redis.setex.return_value = True
    redis.incr.return_value = 1
    redis.expire.return_value = True
    return redis


@pytest_asyncio.fixture
async def app(db_session: AsyncSession, mock_redis) -> FastAPI:
    """Create a test application with overridden dependencies."""
    application = create_application()

    # Override database dependency
    async def override_get_db():
        yield db_session

    application.dependency_overrides[get_db] = override_get_db
    application.state.redis = mock_redis

    return application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async test client for making HTTP requests."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ── Test Data Factories ───────────────────────────────────────────

@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create and persist a test user with a checking account."""
    user = User(
        id=uuid.uuid4(),
        email="testuser@sentinelstream.test",
        hashed_password=get_password_hash("TestPass1!"),
        full_name="Test User",
        role=UserRole.VIEWER,
        home_country="USA",
        home_city="New York",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    account = Account(
        id=uuid.uuid4(),
        user_id=user.id,
        account_number="SS123456789TEST",
        account_type="checking",
        balance=Decimal("10000.00"),
        currency="USD",
        is_active=True,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(user)

    user._test_account = account  # Attach for convenience
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create and persist an admin test user."""
    user = User(
        id=uuid.uuid4(),
        email="admin@sentinelstream.test",
        hashed_password=get_password_hash("AdminPass1!"),
        full_name="Admin User",
        role=UserRole.ADMIN,
        home_country="USA",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_merchant(db_session: AsyncSession) -> Merchant:
    """Create and persist a test merchant."""
    merchant = Merchant(
        id=uuid.uuid4(),
        name="Test Merchant Inc.",
        category="retail",
        country="USA",
        city="New York",
        webhook_url="https://merchant.test/webhooks",
        is_active=True,
    )
    db_session.add(merchant)
    await db_session.commit()
    await db_session.refresh(merchant)
    return merchant


@pytest.fixture
def user_token(test_user: User) -> str:
    """Generate a valid JWT access token for the test user."""
    return create_access_token(str(test_user.id))


@pytest.fixture
def admin_token(admin_user: User) -> str:
    """Generate a valid JWT access token for the admin user."""
    return create_access_token(str(admin_user.id))


@pytest.fixture
def auth_headers(user_token: str) -> dict:
    """Authorization headers for authenticated test requests."""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def admin_headers(admin_token: str) -> dict:
    """Authorization headers for admin test requests."""
    return {"Authorization": f"Bearer {admin_token}"}
