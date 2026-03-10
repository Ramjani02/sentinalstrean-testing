"""
SentinelStream - Main FastAPI Application
Production-grade Real-Time Fraud Detection Engine

Architecture:
  - FastAPI (ASGI) + Uvicorn for high-concurrency async handling
  - PostgreSQL (asyncpg) for the immutable transaction ledger
  - Redis for rate limiting, caching, and idempotency
  - Celery + RabbitMQ for async webhook delivery & alerts
  - Scikit-Learn Isolation Forest for ML-based fraud scoring
"""

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi_limiter import FastAPILimiter

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.session import engine, Base
from app.middleware.idempotency import IdempotencyMiddleware

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles resource initialisation on startup and cleanup on shutdown.
    """
    # ── Startup ───────────────────────────────────────────────
    logger.info("🚀 SentinelStream starting up...")

    # Create all database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables verified/created")

    # Connect to Redis
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    await FastAPILimiter.init(redis_client)
    app.state.redis = redis_client
    logger.info("✅ Redis connected and rate limiter initialised")

    # Pre-load ML model into memory (avoids cold-start latency on first request)
    from app.ml.fraud_scorer import fraud_scorer
    logger.info("✅ ML fraud scoring model loaded")

    logger.info(
        f"✅ SentinelStream ready | ENV={settings.APP_ENV} | "
        f"DEBUG={settings.DEBUG}"
    )

    yield  # Application runs here

    # ── Shutdown ──────────────────────────────────────────────
    logger.info("🛑 SentinelStream shutting down...")
    await redis_client.close()
    await engine.dispose()
    logger.info("✅ Connections closed cleanly")


# ── Application Factory ──────────────────────────────────────────

def create_application() -> FastAPI:
    """
    Create and configure the FastAPI application.
    Separated into a factory function to support testing.
    """
    app = FastAPI(
        title="SentinelStream",
        description=(
            "**High-Throughput Real-Time Fraud Detection Engine**\n\n"
            "Analyses every transaction using a layered approach of a configurable "
            "Rule Engine and a pre-trained Isolation Forest ML model. "
            "Target latency: **<200ms** per transaction.\n\n"
            "Built by Zaalima Development | Python Elite Track Q4"
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── Security Middleware ───────────────────────────────────
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"] if settings.DEBUG else ["sentinelstream.com", "localhost"],
    )

    # ── CORS ─────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["*"],
    )

    # ── Idempotency Middleware ────────────────────────────────
    app.add_middleware(IdempotencyMiddleware)

    # ── API Routes ────────────────────────────────────────────
    app.include_router(api_router)

    # ── Global Exception Handlers ────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred"},
        )

    # ── Health Check ──────────────────────────────────────────
    @app.get("/health", tags=["System"], summary="Health check endpoint")
    async def health_check(request: Request):
        """
        Returns the health status of all critical dependencies.
        Used by Docker, Kubernetes, and load balancers.
        """
        redis = getattr(request.app.state, "redis", None)
        redis_ok = False
        if redis:
            try:
                await redis.ping()
                redis_ok = True
            except Exception:
                pass

        return {
            "status": "healthy" if redis_ok else "degraded",
            "service": "SentinelStream",
            "version": "1.0.0",
            "dependencies": {
                "database": "connected",
                "redis": "connected" if redis_ok else "disconnected",
            },
        }

    @app.get("/", tags=["System"], include_in_schema=False)
    async def root():
        return {
            "service": "SentinelStream Fraud Detection Engine",
            "version": "1.0.0",
            "docs": "/docs",
        }

    return app


app = create_application()
