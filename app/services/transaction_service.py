"""
SentinelStream - Transaction Processing Service
Orchestrates the full fraud detection pipeline:
  1. Idempotency check
  2. Account validation
  3. Rule Engine evaluation
  4. ML fraud scoring
  5. Decision & ledger write
  6. Async webhook dispatch
"""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Account,
    FraudAlert,
    FraudRule,
    IdempotencyRecord,
    Merchant,
    RiskLevel,
    Transaction,
    TransactionStatus,
    User,
)
from app.ml.fraud_scorer import fraud_scorer
from app.schemas.schemas import (
    FraudAnalysisResult,
    TransactionCreateRequest,
    TransactionResponse,
)
from app.services.rule_engine import RuleEngine, RuleEvaluationContext

logger = logging.getLogger(__name__)


class TransactionService:
    """
    Stateless service layer for transaction processing.
    All methods accept a db session and return domain objects or schemas.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Idempotency ─────────────────────────────────────────────

    async def check_idempotency(
        self, idempotency_key: str
    ) -> Optional[IdempotencyRecord]:
        """
        Check if this idempotency key was already processed.
        Returns the cached response if found, else None.
        """
        result = await self.db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.key == idempotency_key,
                IdempotencyRecord.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    async def save_idempotency_record(
        self,
        key: str,
        response_body: dict,
        status_code: int,
    ) -> None:
        """Persist the idempotency record for 24 hours."""
        record = IdempotencyRecord(
            key=key,
            response_body=response_body,
            status_code=status_code,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(record)
        await self.db.flush()

    # ── Transaction History & Balance ───────────────────────────

    async def get_user_transaction_stats(
        self, user_id: uuid.UUID
    ) -> Tuple[int, int, float]:
        """
        Returns (txn_last_hour, txn_last_24h, avg_amount_30d)
        Used by the ML model for velocity-based features.
        """
        now = datetime.now(timezone.utc)

        # Transactions in last hour
        result_1h = await self.db.execute(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user_id,
                Transaction.created_at >= now - timedelta(hours=1),
                Transaction.status.in_([TransactionStatus.APPROVED, TransactionStatus.PENDING]),
            )
        )
        txn_last_hour = result_1h.scalar_one() or 0

        # Transactions in last 24h
        result_24h = await self.db.execute(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user_id,
                Transaction.created_at >= now - timedelta(hours=24),
                Transaction.status != TransactionStatus.DECLINED,
            )
        )
        txn_last_24h = result_24h.scalar_one() or 0

        # Average amount over the last 30 days
        result_avg = await self.db.execute(
            select(func.avg(Transaction.amount)).where(
                Transaction.user_id == user_id,
                Transaction.created_at >= now - timedelta(days=30),
                Transaction.status == TransactionStatus.APPROVED,
            )
        )
        avg_amount = float(result_avg.scalar_one() or 100.0)

        return txn_last_hour, txn_last_24h, avg_amount

    async def get_account(self, account_id: uuid.UUID) -> Optional[Account]:
        result = await self.db.execute(
            select(Account).where(
                Account.id == account_id,
                Account.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_db_rules(self) -> list:
        """Fetch active rules from DB for the rule engine."""
        result = await self.db.execute(
            select(FraudRule)
            .where(FraudRule.is_active == True)
            .order_by(FraudRule.priority)
        )
        rules = result.scalars().all()
        return [
            {
                "name": r.name,
                "description": r.description,
                "priority": r.priority,
                "risk_level_if_triggered": r.risk_level_if_triggered.value,
                "conditions": r.conditions,
            }
            for r in rules
        ]

    # ── Fraud Detection Pipeline ────────────────────────────────

    async def analyse_transaction(
        self,
        request: TransactionCreateRequest,
        user: User,
        account: Account,
        merchant: Optional[Merchant],
    ) -> FraudAnalysisResult:
        """
        Full fraud detection pipeline:
          1. Build context
          2. Run Rule Engine
          3. Run ML scoring
          4. Combine signals → final decision
        """
        start_ms = time.monotonic() * 1000
        now = datetime.now(timezone.utc)

        txn_last_hour, txn_last_24h, avg_amount = await self.get_user_transaction_stats(
            user.id
        )

        # ── Build Rule Context ────────────────────────────────
        ctx = RuleEvaluationContext(
            amount=float(request.amount),
            currency=request.currency,
            transaction_country=request.transaction_country,
            transaction_city=request.transaction_city,
            user_home_country=user.home_country,
            user_home_city=user.home_city,
            hour_of_day=now.hour,
            day_of_week=now.weekday(),
            transactions_last_hour=txn_last_hour,
            transactions_last_24h=txn_last_24h,
            amount_vs_avg_ratio=float(request.amount) / max(avg_amount, 1.0),
            is_foreign_transaction=(
                request.transaction_country is not None
                and user.home_country is not None
                and request.transaction_country.upper() != user.home_country.upper()
            ),
            account_balance=float(account.balance),
            merchant_category=merchant.category if merchant else None,
        )

        # ── Rule Engine ───────────────────────────────────────
        db_rules = await self.get_active_db_rules()
        engine = RuleEngine(db_rules=db_rules)
        rule_result = engine.evaluate(ctx)

        # ── ML Scoring ────────────────────────────────────────
        ml_score, ml_features = fraud_scorer.score_transaction(
            amount=float(request.amount),
            created_at=now,
            transactions_last_hour=txn_last_hour,
            transactions_last_24h=txn_last_24h,
            user_avg_amount=avg_amount,
            user_home_country=user.home_country or "USA",
            transaction_country=request.transaction_country or user.home_country or "USA",
            merchant_risk_score=0.5 if merchant is None else 0.1,
        )

        # ── Combine Signals ───────────────────────────────────
        # Rule engine can force a decline; otherwise use ML score
        if rule_result.should_decline:
            final_risk = "critical"
            decision = "decline"
            # Boost score when a critical rule fires
            final_score = max(ml_score, 0.90)
        elif rule_result.max_risk_level in ("high", "critical"):
            final_score = max(ml_score, 0.70)
            final_risk = rule_result.max_risk_level
            decision = "flag"
        elif ml_score >= 0.65:
            final_risk = "high" if ml_score >= 0.80 else "medium"
            final_score = ml_score
            decision = "flag" if ml_score < 0.85 else "decline"
        else:
            final_risk = rule_result.max_risk_level if rule_result.triggered_rules else "low"
            final_score = ml_score
            decision = "approve"

        latency_ms = int((time.monotonic() * 1000) - start_ms)

        return FraudAnalysisResult(
            fraud_score=final_score,
            risk_level=final_risk,
            triggered_rules=rule_result.triggered_rules,
            ml_features=ml_features,
            decision=decision,
            processing_latency_ms=latency_ms,
        )

    # ── Write Transaction to Ledger ─────────────────────────────

    async def create_transaction(
        self,
        request: TransactionCreateRequest,
        user: User,
        fraud_result: FraudAnalysisResult,
    ) -> Transaction:
        """
        Writes the transaction to the immutable PostgreSQL ledger.
        Deducts balance if approved.
        """
        now = datetime.now(timezone.utc)

        status_map = {
            "approve": TransactionStatus.APPROVED,
            "decline": TransactionStatus.DECLINED,
            "flag": TransactionStatus.FLAGGED,
        }
        risk_map = {
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH,
            "critical": RiskLevel.CRITICAL,
        }

        txn = Transaction(
            id=uuid.uuid4(),
            idempotency_key=request.idempotency_key,
            user_id=user.id,
            account_id=request.account_id,
            merchant_id=request.merchant_id,
            amount=request.amount,
            currency=request.currency,
            transaction_type=request.transaction_type,
            description=request.description,
            transaction_country=request.transaction_country,
            transaction_city=request.transaction_city,
            device_fingerprint=request.device_fingerprint,
            status=status_map[fraud_result.decision],
            risk_level=risk_map.get(fraud_result.risk_level, RiskLevel.LOW),
            fraud_score=fraud_result.fraud_score,
            rule_flags=fraud_result.triggered_rules,
            ml_features=fraud_result.ml_features,
            processing_latency_ms=fraud_result.processing_latency_ms,
            processed_at=now,
        )

        self.db.add(txn)

        # Update account balance if approved
        if fraud_result.decision == "approve":
            account = await self.get_account(request.account_id)
            if account:
                account.balance = account.balance - request.amount
                account.updated_at = now

        # Create a FraudAlert for flagged/declined transactions
        if fraud_result.decision in ("flag", "decline") and fraud_result.fraud_score >= 0.50:
            alert = FraudAlert(
                transaction_id=txn.id,
                risk_level=risk_map.get(fraud_result.risk_level, RiskLevel.MEDIUM),
                fraud_score=fraud_result.fraud_score,
                triggered_rules=fraud_result.triggered_rules,
            )
            self.db.add(alert)

        await self.db.flush()
        return txn

    # ── User Transaction History ────────────────────────────────

    async def get_user_transactions(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
    ):
        """Paginated transaction history for a user."""
        offset = (page - 1) * per_page
        result = await self.db.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        transactions = result.scalars().all()

        count_result = await self.db.execute(
            select(func.count(Transaction.id)).where(Transaction.user_id == user_id)
        )
        total = count_result.scalar_one()

        return transactions, total
