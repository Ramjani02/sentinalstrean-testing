"""
SentinelStream - Database ORM Models
Star Schema design optimised for transaction analytics and fraud detection queries.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums ────────────────────────────────────────────────────────
import enum


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    FLAGGED = "flagged"
    REVERSED = "reversed"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class WebhookStatus(str, enum.Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


# ── Dimension Tables (Star Schema) ───────────────────────────────

class User(Base):
    """
    Represents a bank customer. Stores hashed credentials,
    profile data, and account metadata.
    """
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=False)
    full_name = Column(String(200), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.VIEWER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)

    # Profile / risk context
    home_country = Column(String(3), nullable=True)       # ISO 3166-1 alpha-3
    home_city = Column(String(100), nullable=True)
    typical_spend_limit = Column(Numeric(12, 2), default=5000.00)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user")

    __table_args__ = (
        Index("ix_users_email_active", "email", "is_active"),
    )


class Account(Base):
    """
    A bank account linked to a User.
    Tracks the current balance and account type.
    """
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_number = Column(String(20), unique=True, nullable=False)
    account_type = Column(String(20), default="checking", nullable=False)
    balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")


class Merchant(Base):
    """Represents a merchant entity in the payment ecosystem."""
    __tablename__ = "merchants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=True)           # MCC code / label
    country = Column(String(3), nullable=True)
    city = Column(String(100), nullable=True)
    webhook_url = Column(String(500), nullable=True)        # Where to send status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    transactions = relationship("Transaction", back_populates="merchant")


# ── Fact Table ───────────────────────────────────────────────────

class Transaction(Base):
    """
    FACT TABLE - The core of the Star Schema.
    Every financial transaction flows through this table.
    Immutable after creation (append-only ledger pattern).
    """
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Star Schema Foreign Keys
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=True)

    # Idempotency key - prevents duplicate processing
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)

    # Transaction data
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    transaction_type = Column(String(30), default="purchase", nullable=False)
    description = Column(String(500), nullable=True)

    # Location context (for geo-based fraud rules)
    transaction_country = Column(String(3), nullable=True)
    transaction_city = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)           # Supports IPv6
    device_fingerprint = Column(String(200), nullable=True)

    # Status & fraud scoring
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False)
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.LOW, nullable=True)
    fraud_score = Column(Float, nullable=True)               # 0.0 → 1.0 from ML model
    rule_flags = Column(JSONB, default=list)                 # List of triggered rule names
    ml_features = Column(JSONB, nullable=True)               # Features sent to ML model

    # Processing metadata
    processed_at = Column(DateTime(timezone=True), nullable=True)
    processing_latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="transactions")
    account = relationship("Account", back_populates="transactions")
    merchant = relationship("Merchant", back_populates="transactions")
    fraud_alert = relationship("FraudAlert", back_populates="transaction", uselist=False)
    webhooks = relationship("WebhookDelivery", back_populates="transaction")

    __table_args__ = (
        Index("ix_transactions_user_created", "user_id", "created_at"),
        Index("ix_transactions_status_created", "status", "created_at"),
        Index("ix_transactions_fraud_score", "fraud_score"),
    )


# ── Supporting Tables ────────────────────────────────────────────

class FraudAlert(Base):
    """
    Created when a transaction is flagged as HIGH or CRITICAL risk.
    Drives analyst review workflow.
    """
    __tablename__ = "fraud_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    risk_level = Column(Enum(RiskLevel), nullable=False)
    fraud_score = Column(Float, nullable=False)
    triggered_rules = Column(JSONB, default=list)
    analyst_notes = Column(Text, nullable=True)
    resolved = Column(Boolean, default=False)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    transaction = relationship("Transaction", back_populates="fraud_alert")


class FraudRule(Base):
    """
    Configurable fraud detection rules manageable by non-technical staff.
    Rules are evaluated in priority order against each transaction.
    """
    __tablename__ = "fraud_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    priority = Column(Integer, default=100)                  # Lower = evaluated first

    # Rule conditions stored as JSON for flexibility
    # Example: {"field": "amount", "operator": ">", "value": 5000}
    conditions = Column(JSONB, nullable=False)
    risk_level_if_triggered = Column(Enum(RiskLevel), default=RiskLevel.HIGH)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebhookDelivery(Base):
    """
    Tracks asynchronous webhook notifications sent to merchants.
    Supports retry logic via Celery.
    """
    __tablename__ = "webhook_deliveries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    webhook_url = Column(String(500), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(Enum(WebhookStatus), default=WebhookStatus.PENDING, nullable=False)
    attempt_count = Column(Integer, default=0)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    transaction = relationship("Transaction", back_populates="webhooks")


class IdempotencyRecord(Base):
    """
    Stores processed idempotency keys to prevent duplicate transaction processing.
    Records expire after 24 hours (managed by a Celery beat task).
    """
    __tablename__ = "idempotency_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    response_body = Column(JSONB, nullable=False)
    status_code = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_idempotency_expires", "expires_at"),
    )
