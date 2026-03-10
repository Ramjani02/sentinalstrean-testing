"""
SentinelStream - Application Configuration
All settings are loaded from environment variables with sensible defaults.
"""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object. Values are read from environment variables
    or the .env file. Never hard-code secrets — always use this class.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────
    APP_NAME: str = "SentinelStream"
    APP_ENV: str = "development"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change-me-in-production"

    # ── JWT ──────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-jwt-secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Database ─────────────────────────────────────────────────
    DATABASE_URL: str = (
        "postgresql+asyncpg://sentinel:sentinel_secret@localhost:5432/sentinelstream"
    )

    # ── Redis ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://:redis_secret@localhost:6379/0"
    REDIS_PASSWORD: str = "redis_secret"

    # ── Celery / RabbitMQ ────────────────────────────────────────
    CELERY_BROKER_URL: str = "amqp://sentinel:rabbit_secret@localhost:5672//"
    CELERY_RESULT_BACKEND: str = "redis://:redis_secret@localhost:6379/1"

    # ── Rate Limiting ────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 100
    RATE_LIMIT_BURST: int = 200

    # ── ML ───────────────────────────────────────────────────────
    ML_MODEL_PATH: str = "ml_models/isolation_forest.joblib"
    ML_SCALER_PATH: str = "ml_models/scaler.joblib"
    FRAUD_SCORE_THRESHOLD: float = 0.65

    # ── Email ────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    ALERT_EMAIL_FROM: str = "alerts@sentinelstream.com"
    ALERT_EMAIL_TO: str = "fraud_team@yourbank.com"

    # ── CORS ─────────────────────────────────────────────────────
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache()
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.
    Use this function via FastAPI's Depends() for dependency injection.
    """
    return Settings()


# Module-level singleton for use outside of FastAPI DI
settings = get_settings()
