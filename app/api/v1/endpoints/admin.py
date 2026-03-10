"""
SentinelStream - Admin Endpoints
Fraud rule management and analytics for admin/analyst users.

GET  /admin/stats          - Transaction statistics dashboard
GET  /admin/alerts         - List unresolved fraud alerts
PUT  /admin/alerts/{id}    - Resolve a fraud alert
POST /admin/rules          - Create a new fraud rule
GET  /admin/rules          - List all fraud rules
PUT  /admin/rules/{id}     - Update a fraud rule
DELETE /admin/rules/{id}   - Deactivate a fraud rule
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin, require_analyst_or_above
from app.db.session import get_db
from app.models.models import (
    FraudAlert,
    FraudRule,
    RiskLevel,
    Transaction,
    TransactionStatus,
    User,
)
from app.schemas.schemas import (
    FraudRuleCreateRequest,
    FraudRuleResponse,
    TransactionStats,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get(
    "/stats",
    response_model=TransactionStats,
    summary="Transaction analytics dashboard",
)
async def get_stats(
    hours: int = Query(default=24, ge=1, le=720, description="Lookback window in hours"),
    current_user: User = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
) -> TransactionStats:
    """Aggregated transaction statistics for the specified time window."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    base_query = select(Transaction).where(Transaction.created_at >= since)

    # Total count
    total_result = await db.execute(
        select(func.count(Transaction.id)).where(Transaction.created_at >= since)
    )
    total = total_result.scalar_one() or 0

    # Volume
    vol_result = await db.execute(
        select(func.sum(Transaction.amount)).where(Transaction.created_at >= since)
    )
    total_volume = vol_result.scalar_one() or Decimal("0")

    # By status
    flagged = await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.created_at >= since,
            Transaction.status == TransactionStatus.FLAGGED,
        )
    )
    declined = await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.created_at >= since,
            Transaction.status == TransactionStatus.DECLINED,
        )
    )
    approved = await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.created_at >= since,
            Transaction.status == TransactionStatus.APPROVED,
        )
    )

    # Avg fraud score
    avg_score = await db.execute(
        select(func.avg(Transaction.fraud_score)).where(
            Transaction.created_at >= since,
            Transaction.fraud_score.isnot(None),
        )
    )

    # High risk count
    high_risk = await db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.created_at >= since,
            Transaction.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL]),
        )
    )

    return TransactionStats(
        total_transactions=total,
        total_volume=total_volume,
        flagged_count=flagged.scalar_one() or 0,
        declined_count=declined.scalar_one() or 0,
        approved_count=approved.scalar_one() or 0,
        avg_fraud_score=round(float(avg_score.scalar_one() or 0), 4),
        high_risk_count=high_risk.scalar_one() or 0,
        period_hours=hours,
    )


@router.get(
    "/alerts",
    summary="List unresolved fraud alerts",
)
async def list_alerts(
    resolved: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
):
    """List fraud alerts for analyst review."""
    offset = (page - 1) * per_page
    result = await db.execute(
        select(FraudAlert)
        .where(FraudAlert.resolved == resolved)
        .order_by(FraudAlert.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    alerts = result.scalars().all()
    return {"alerts": alerts, "page": page, "per_page": per_page}


@router.put(
    "/alerts/{alert_id}/resolve",
    summary="Mark a fraud alert as resolved",
)
async def resolve_alert(
    alert_id: uuid.UUID,
    notes: str = "",
    current_user: User = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a fraud alert and add analyst notes."""
    result = await db.execute(
        select(FraudAlert).where(FraudAlert.id == alert_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.resolved = True
    alert.resolved_by = current_user.id
    alert.resolved_at = datetime.now(timezone.utc)
    alert.analyst_notes = notes
    await db.commit()

    return {"message": "Alert resolved", "alert_id": str(alert_id)}


# ── Fraud Rule Management ─────────────────────────────────────────

@router.post(
    "/rules",
    response_model=FraudRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new fraud detection rule",
)
async def create_rule(
    request: FraudRuleCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FraudRuleResponse:
    """
    Create a configurable fraud rule. No redeployment required.
    Rules are applied to all subsequent transactions in real time.
    """
    # Check unique name
    existing = await db.execute(
        select(FraudRule).where(FraudRule.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A rule named '{request.name}' already exists",
        )

    rule = FraudRule(
        name=request.name,
        description=request.description,
        priority=request.priority,
        conditions=[c.model_dump() for c in request.conditions],
        risk_level_if_triggered=RiskLevel(request.risk_level_if_triggered),
        is_active=True,
        created_by=current_user.id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    return FraudRuleResponse.model_validate(rule)


@router.get(
    "/rules",
    response_model=list[FraudRuleResponse],
    summary="List all fraud detection rules",
)
async def list_rules(
    active_only: bool = Query(default=False),
    current_user: User = Depends(require_analyst_or_above),
    db: AsyncSession = Depends(get_db),
) -> list[FraudRuleResponse]:
    """Return all configured fraud rules, optionally filtered to active only."""
    query = select(FraudRule).order_by(FraudRule.priority)
    if active_only:
        query = query.where(FraudRule.is_active == True)

    result = await db.execute(query)
    rules = result.scalars().all()
    return [FraudRuleResponse.model_validate(r) for r in rules]


@router.put(
    "/rules/{rule_id}",
    response_model=FraudRuleResponse,
    summary="Update an existing fraud rule",
)
async def update_rule(
    rule_id: int,
    request: FraudRuleCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FraudRuleResponse:
    """Update rule conditions, priority, or description."""
    result = await db.execute(select(FraudRule).where(FraudRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.name = request.name
    rule.description = request.description
    rule.priority = request.priority
    rule.conditions = [c.model_dump() for c in request.conditions]
    rule.risk_level_if_triggered = RiskLevel(request.risk_level_if_triggered)
    await db.commit()
    await db.refresh(rule)

    return FraudRuleResponse.model_validate(rule)


@router.delete(
    "/rules/{rule_id}",
    summary="Deactivate a fraud rule",
)
async def deactivate_rule(
    rule_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete: deactivates the rule without removing it from the database."""
    result = await db.execute(select(FraudRule).where(FraudRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.is_active = False
    await db.commit()

    return {"message": f"Rule '{rule.name}' deactivated", "rule_id": rule_id}
