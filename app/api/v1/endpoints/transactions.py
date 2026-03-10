"""
SentinelStream - Transaction Endpoints
POST /transactions           - Submit a transaction for fraud analysis
GET  /transactions           - Get current user's transaction history
GET  /transactions/{id}      - Get a single transaction detail
GET  /transactions/balance   - Get account balance
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.models import Account, Merchant, User
from app.schemas.schemas import (
    AccountResponse,
    BalanceResponse,
    TransactionCreateRequest,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.transaction_service import TransactionService
from app.tasks.celery_app import deliver_webhook, send_fraud_alert_email

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a transaction for real-time fraud analysis",
    description="""
    The core SentinelStream endpoint.

    **Idempotency**: Include an `Idempotency-Key` header with a unique
    client-generated string to prevent duplicate charges on retry.

    **Processing pipeline** (target: <200ms):
    1. Idempotency check
    2. Account validation
    3. Rule Engine evaluation
    4. Isolation Forest ML scoring
    5. Decision (approve / flag / decline)
    6. Ledger write to PostgreSQL
    7. Async webhook dispatch via Celery (non-blocking)
    """,
)
async def create_transaction(
    request_body: TransactionCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    """
    Submit a new transaction. Returns the full transaction record
    including fraud score, risk level, and processing decision.
    """
    service = TransactionService(db)

    # ── 1. Idempotency guard ─────────────────────────────────
    existing = await service.check_idempotency(request_body.idempotency_key)
    if existing:
        # Return the cached response — do NOT re-process
        from sqlalchemy import select as sa_select
        from app.models.models import Transaction
        result = await db.execute(
            sa_select(Transaction).where(
                Transaction.idempotency_key == request_body.idempotency_key
            )
        )
        cached_txn = result.scalar_one_or_none()
        if cached_txn:
            return TransactionResponse.model_validate(cached_txn)

    # ── 2. Validate account ownership ───────────────────────
    account = await service.get_account(request_body.account_id)
    if not account or account.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found or does not belong to this user",
        )
    if not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Account is not active",
        )

    # ── 3. Resolve merchant (optional) ──────────────────────
    merchant = None
    if request_body.merchant_id:
        result = await db.execute(
            select(Merchant).where(Merchant.id == request_body.merchant_id)
        )
        merchant = result.scalar_one_or_none()

    # ── 4. Fraud detection pipeline ─────────────────────────
    fraud_result = await service.analyse_transaction(
        request=request_body,
        user=current_user,
        account=account,
        merchant=merchant,
    )

    # ── 5. Write to ledger ──────────────────────────────────
    transaction = await service.create_transaction(
        request=request_body,
        user=current_user,
        fraud_result=fraud_result,
    )

    # ── 6. Save idempotency record ──────────────────────────
    response = TransactionResponse.model_validate(transaction)
    await service.save_idempotency_record(
        key=request_body.idempotency_key,
        response_body=response.model_dump(mode="json"),
        status_code=201,
    )

    await db.commit()
    await db.refresh(transaction)

    # ── 7. Async side-effects (non-blocking) ─────────────────
    # Dispatch webhook to merchant
    if merchant and merchant.webhook_url:
        deliver_webhook.delay(
            webhook_delivery_id=str(uuid.uuid4()),
            webhook_url=merchant.webhook_url,
            payload={
                "event": "transaction.processed",
                "transaction_id": str(transaction.id),
                "status": transaction.status.value,
                "amount": float(transaction.amount),
                "currency": transaction.currency,
                "fraud_score": transaction.fraud_score,
                "risk_level": transaction.risk_level.value if transaction.risk_level else "low",
            },
        )

    # Send fraud alert email for high/critical risk
    if transaction.risk_level and transaction.risk_level.value in ("high", "critical"):
        send_fraud_alert_email.delay(
            transaction_id=str(transaction.id),
            user_email=current_user.email,
            user_name=current_user.full_name,
            amount=float(transaction.amount),
            currency=transaction.currency,
            fraud_score=transaction.fraud_score or 0.0,
            risk_level=transaction.risk_level.value,
            triggered_rules=transaction.rule_flags or [],
        )

    return TransactionResponse.model_validate(transaction)


@router.get(
    "",
    response_model=TransactionListResponse,
    summary="Get authenticated user's transaction history",
)
async def list_transactions(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionListResponse:
    """Paginated transaction history for the authenticated user."""
    service = TransactionService(db)
    transactions, total = await service.get_user_transactions(
        user_id=current_user.id,
        page=page,
        per_page=per_page,
    )
    return TransactionListResponse(
        transactions=[TransactionResponse.model_validate(t) for t in transactions],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/balance",
    response_model=list[BalanceResponse],
    summary="Get all account balances for the authenticated user",
)
async def get_balance(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[BalanceResponse]:
    """Return current balances for all accounts belonging to the user."""
    result = await db.execute(
        select(Account).where(
            Account.user_id == current_user.id,
            Account.is_active == True,
        )
    )
    accounts = result.scalars().all()

    return [
        BalanceResponse(
            account_id=acc.id,
            account_number=acc.account_number,
            balance=acc.balance,
            currency=acc.currency,
            available_balance=acc.balance,  # Simplified: no pending holds
        )
        for acc in accounts
    ]


@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Get a single transaction by ID",
)
async def get_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    """
    Fetch a transaction by ID. Users can only view their own transactions.
    """
    from app.models.models import Transaction
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == current_user.id,
        )
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )
    return TransactionResponse.model_validate(txn)
