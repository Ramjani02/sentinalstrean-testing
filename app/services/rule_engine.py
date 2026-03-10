"""
SentinelStream - Dynamic Rule Engine
Evaluates a set of configurable fraud rules against each transaction.
Rules are loaded from the database and cached in Redis for performance.

Non-technical staff can add/edit rules via the Admin API without redeployment.
"""

import logging
import operator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Operator Map ─────────────────────────────────────────────────
OPERATOR_MAP = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    "in": lambda x, y: x in y,
    "not_in": lambda x, y: x not in y,
    "contains": lambda x, y: y in str(x),
}

RISK_LEVEL_WEIGHTS = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


@dataclass
class RuleEvaluationContext:
    """
    All fields available for rule evaluation.
    Constructed from the incoming transaction + user profile.
    """
    amount: float
    currency: str
    transaction_country: Optional[str]
    transaction_city: Optional[str]
    user_home_country: Optional[str]
    user_home_city: Optional[str]
    hour_of_day: int
    day_of_week: int
    transactions_last_hour: int
    transactions_last_24h: int
    amount_vs_avg_ratio: float
    is_foreign_transaction: bool
    account_balance: float
    merchant_category: Optional[str] = None
    device_fingerprint: Optional[str] = None


@dataclass
class RuleResult:
    """Outcome of evaluating a single rule."""
    rule_name: str
    triggered: bool
    risk_level: str
    reason: str = ""


@dataclass
class RuleEngineResult:
    """Aggregated outcome from running all rules."""
    triggered_rules: List[str] = field(default_factory=list)
    max_risk_level: str = "low"
    should_decline: bool = False
    details: List[RuleResult] = field(default_factory=list)


class RuleEngine:
    """
    Evaluates a prioritised list of fraud detection rules against
    a transaction context.

    Rules are JSON-encoded condition lists, e.g.:
        [
            {"field": "amount", "operator": ">", "value": 5000},
            {"field": "transaction_country", "operator": "!=", "value": "USA"}
        ]
    Multiple conditions are combined with AND logic.
    """

    # Built-in system rules (always active, cannot be deleted via API)
    SYSTEM_RULES = [
        {
            "name": "high_amount_foreign",
            "description": "High value transaction from a foreign country",
            "priority": 10,
            "risk_level_if_triggered": "high",
            "conditions": [
                {"field": "amount", "operator": ">", "value": 5000},
                {"field": "is_foreign_transaction", "operator": "==", "value": True},
            ],
        },
        {
            "name": "velocity_attack",
            "description": "More than 5 transactions in the last hour — possible card testing",
            "priority": 5,
            "risk_level_if_triggered": "critical",
            "conditions": [
                {"field": "transactions_last_hour", "operator": ">", "value": 5},
            ],
        },
        {
            "name": "overnight_large_transaction",
            "description": "Large transaction placed between midnight and 4 AM",
            "priority": 20,
            "risk_level_if_triggered": "medium",
            "conditions": [
                {"field": "amount", "operator": ">", "value": 1000},
                {"field": "hour_of_day", "operator": "<", "value": 4},
            ],
        },
        {
            "name": "extreme_amount_spike",
            "description": "Transaction amount is 10x the user's average",
            "priority": 15,
            "risk_level_if_triggered": "critical",
            "conditions": [
                {"field": "amount_vs_avg_ratio", "operator": ">", "value": 10},
            ],
        },
        {
            "name": "exceeds_balance",
            "description": "Transaction amount exceeds available account balance",
            "priority": 1,
            "risk_level_if_triggered": "critical",
            "conditions": [
                {"field": "amount", "operator": ">", "value": "account_balance"},
            ],
        },
    ]

    def __init__(self, db_rules: Optional[List[Dict]] = None):
        """
        Args:
            db_rules: Rules fetched from the database. Merged with SYSTEM_RULES.
        """
        all_rules = list(self.SYSTEM_RULES)
        if db_rules:
            all_rules.extend(db_rules)
        # Sort by priority ascending (lower number = evaluated first)
        self._rules = sorted(all_rules, key=lambda r: r.get("priority", 100))

    def _evaluate_condition(
        self, condition: Dict[str, Any], ctx: RuleEvaluationContext
    ) -> bool:
        """
        Evaluate a single condition against the context.
        Supports field references as values (e.g., value: "account_balance").
        """
        field_name = condition["field"]
        op_str = condition["operator"]
        raw_value = condition["value"]

        # Get the field value from context
        ctx_value = getattr(ctx, field_name, None)
        if ctx_value is None:
            return False

        # Resolve value references (allows rules like amount > account_balance)
        if isinstance(raw_value, str) and hasattr(ctx, raw_value):
            compare_value = getattr(ctx, raw_value)
        else:
            compare_value = raw_value

        op_fn = OPERATOR_MAP.get(op_str)
        if not op_fn:
            logger.warning(f"Unknown operator in rule: {op_str}")
            return False

        try:
            return op_fn(float(ctx_value) if isinstance(ctx_value, (int, float, Decimal)) else ctx_value, compare_value)
        except Exception as e:
            logger.error(f"Rule condition evaluation error: {e}")
            return False

    def evaluate(self, ctx: RuleEvaluationContext) -> RuleEngineResult:
        """
        Run all rules against the provided context.

        Returns:
            RuleEngineResult with all triggered rules and the highest risk level.
        """
        result = RuleEngineResult()
        max_weight = RISK_LEVEL_WEIGHTS["low"]

        for rule in self._rules:
            conditions = rule.get("conditions", [])
            # All conditions must pass (AND logic)
            all_passed = all(
                self._evaluate_condition(cond, ctx) for cond in conditions
            )

            rule_result = RuleResult(
                rule_name=rule["name"],
                triggered=all_passed,
                risk_level=rule.get("risk_level_if_triggered", "medium"),
            )
            result.details.append(rule_result)

            if all_passed:
                result.triggered_rules.append(rule["name"])
                weight = RISK_LEVEL_WEIGHTS.get(rule_result.risk_level, 1)
                if weight > max_weight:
                    max_weight = weight
                    result.max_risk_level = rule_result.risk_level
                    # Immediately decline on critical
                    if rule_result.risk_level == "critical":
                        result.should_decline = True

        logger.debug(
            f"Rule engine: {len(result.triggered_rules)} rules triggered. "
            f"Max risk: {result.max_risk_level}"
        )
        return result
