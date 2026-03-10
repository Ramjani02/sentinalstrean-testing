"""
SentinelStream - Pydantic Schemas
Request/response validation with strict type checking.
All monetary values use Decimal for precision.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ── Base Helpers ─────────────────────────────────────────────────

class BaseResponse(BaseModel):
    """Standard API envelope."""
    success: bool = True
    message: str = "OK"


# ── Auth Schemas ─────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    full_name: str = Field(min_length=2, max_length=200)
    home_country: Optional[str] = Field(None, max_length=3)
    home_city: Optional[str] = Field(None, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    is_verified: bool
    home_country: Optional[str]
    home_city: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Account Schemas ───────────────────────────────────────────────

class AccountResponse(BaseModel):
    id: uuid.UUID
    account_number: str
    account_type: str
    balance: Decimal
    currency: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Transaction Schemas ───────────────────────────────────────────

class TransactionCreateRequest(BaseModel):
    """
    Payload for POST /api/v1/transactions.
    The idempotency_key MUST be set by the client to prevent duplicates.
    """
    idempotency_key: str = Field(
        ...,
        min_length=16,
        max_length=128,
        description="Unique client-generated key to prevent duplicate charges.",
        examples=["txn_client_20240101_abc123xyz"],
    )
    account_id: uuid.UUID
    merchant_id: Optional[uuid.UUID] = None
    amount: Decimal = Field(..., gt=0, decimal_places=2, lt=1_000_000)
    currency: str = Field(default="USD", max_length=3)
    transaction_type: str = Field(default="purchase", max_length=30)
    description: Optional[str] = Field(None, max_length=500)

    # Geo context — helps the rule engine detect anomalies
    transaction_country: Optional[str] = Field(None, max_length=3)
    transaction_city: Optional[str] = Field(None, max_length=100)
    device_fingerprint: Optional[str] = Field(None, max_length=200)

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, v: str) -> str:
        return v.upper()

    @field_validator("idempotency_key")
    @classmethod
    def no_whitespace(cls, v: str) -> str:
        if " " in v:
            raise ValueError("Idempotency key must not contain spaces")
        return v


class FraudAnalysisResult(BaseModel):
    """Internal model carrying results from the fraud detection pipeline."""
    fraud_score: float = Field(ge=0.0, le=1.0)
    risk_level: str
    triggered_rules: List[str] = []
    ml_features: Dict[str, Any] = {}
    decision: str                               # "approve" | "decline" | "flag"
    processing_latency_ms: int


class TransactionResponse(BaseModel):
    id: uuid.UUID
    idempotency_key: str
    account_id: uuid.UUID
    merchant_id: Optional[uuid.UUID]
    amount: Decimal
    currency: str
    transaction_type: str
    description: Optional[str]
    status: str
    risk_level: Optional[str]
    fraud_score: Optional[float]
    rule_flags: Optional[List[str]]
    transaction_country: Optional[str]
    transaction_city: Optional[str]
    processing_latency_ms: Optional[int]
    created_at: datetime
    processed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    transactions: List[TransactionResponse]
    total: int
    page: int
    per_page: int


# ── Fraud Rule Schemas ────────────────────────────────────────────

class RuleCondition(BaseModel):
    """A single condition within a fraud rule."""
    field: str = Field(..., examples=["amount", "transaction_country"])
    operator: str = Field(..., examples=[">", "!=", "in", "not_in"])
    value: Any


class FraudRuleCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    description: Optional[str] = None
    priority: int = Field(default=100, ge=1, le=1000)
    conditions: List[RuleCondition]
    risk_level_if_triggered: str = "high"

    @field_validator("risk_level_if_triggered")
    @classmethod
    def valid_risk_level(cls, v: str) -> str:
        valid = {"low", "medium", "high", "critical"}
        if v.lower() not in valid:
            raise ValueError(f"risk_level must be one of {valid}")
        return v.lower()


class FraudRuleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    priority: int
    conditions: List[Dict[str, Any]]
    risk_level_if_triggered: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard / Analytics Schemas ────────────────────────────────

class TransactionStats(BaseModel):
    total_transactions: int
    total_volume: Decimal
    flagged_count: int
    declined_count: int
    approved_count: int
    avg_fraud_score: float
    high_risk_count: int
    period_hours: int


class BalanceResponse(BaseModel):
    account_id: uuid.UUID
    account_number: str
    balance: Decimal
    currency: str
    available_balance: Decimal
