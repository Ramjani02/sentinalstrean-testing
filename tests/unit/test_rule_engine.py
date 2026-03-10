"""
Unit Tests - Rule Engine
Tests every built-in rule and operator in the RuleEngine.
Target: 100% branch coverage of rule_engine.py
"""

import pytest
from app.services.rule_engine import RuleEngine, RuleEvaluationContext


def make_context(**kwargs) -> RuleEvaluationContext:
    """Helper: build a context with safe defaults, overriding with kwargs."""
    defaults = dict(
        amount=100.0,
        currency="USD",
        transaction_country="USA",
        transaction_city="New York",
        user_home_country="USA",
        user_home_city="New York",
        hour_of_day=14,
        day_of_week=1,
        transactions_last_hour=1,
        transactions_last_24h=5,
        amount_vs_avg_ratio=1.0,
        is_foreign_transaction=False,
        account_balance=5000.0,
        merchant_category="retail",
    )
    defaults.update(kwargs)
    return RuleEvaluationContext(**defaults)


class TestRuleEngineBuiltins:

    def test_normal_transaction_no_rules_triggered(self):
        engine = RuleEngine()
        ctx = make_context()
        result = engine.evaluate(ctx)
        assert result.triggered_rules == []
        assert result.max_risk_level == "low"
        assert result.should_decline is False

    def test_velocity_attack_triggers_critical(self):
        """More than 5 txns in the last hour = CRITICAL"""
        engine = RuleEngine()
        ctx = make_context(transactions_last_hour=6)
        result = engine.evaluate(ctx)
        assert "velocity_attack" in result.triggered_rules
        assert result.max_risk_level == "critical"
        assert result.should_decline is True

    def test_high_amount_foreign_triggers_high(self):
        """Amount > $5000 AND foreign transaction = HIGH"""
        engine = RuleEngine()
        ctx = make_context(
            amount=6000.0,
            is_foreign_transaction=True,
        )
        result = engine.evaluate(ctx)
        assert "high_amount_foreign" in result.triggered_rules
        assert result.max_risk_level in ("high", "critical")

    def test_high_amount_not_foreign_does_not_trigger(self):
        """Amount > $5000 but domestic should NOT trigger the foreign rule"""
        engine = RuleEngine()
        ctx = make_context(amount=6000.0, is_foreign_transaction=False)
        result = engine.evaluate(ctx)
        assert "high_amount_foreign" not in result.triggered_rules

    def test_extreme_amount_spike_triggers_critical(self):
        """Amount 10x the user's average = CRITICAL"""
        engine = RuleEngine()
        ctx = make_context(amount_vs_avg_ratio=11.0)
        result = engine.evaluate(ctx)
        assert "extreme_amount_spike" in result.triggered_rules
        assert result.should_decline is True

    def test_overnight_large_transaction_triggers_medium(self):
        """Large txn at 2AM should trigger medium risk"""
        engine = RuleEngine()
        ctx = make_context(amount=1500.0, hour_of_day=2)
        result = engine.evaluate(ctx)
        assert "overnight_large_transaction" in result.triggered_rules

    def test_exceeds_balance_triggers_critical(self):
        """Transaction amount exceeds account balance"""
        engine = RuleEngine()
        ctx = make_context(amount=6000.0, account_balance=100.0)
        result = engine.evaluate(ctx)
        assert "exceeds_balance" in result.triggered_rules
        assert result.should_decline is True

    def test_multiple_rules_highest_risk_wins(self):
        """When multiple rules fire, the highest risk level is reported"""
        engine = RuleEngine()
        ctx = make_context(
            amount=6000.0,
            is_foreign_transaction=True,
            transactions_last_hour=10,  # critical
        )
        result = engine.evaluate(ctx)
        assert result.max_risk_level == "critical"

    def test_custom_db_rule_applied(self):
        """Database-sourced custom rules are merged and evaluated"""
        custom_rules = [
            {
                "name": "casino_merchant",
                "description": "Any casino transaction is flagged",
                "priority": 50,
                "risk_level_if_triggered": "high",
                "conditions": [
                    {"field": "merchant_category", "operator": "==", "value": "casino"}
                ],
            }
        ]
        engine = RuleEngine(db_rules=custom_rules)
        ctx = make_context(merchant_category="casino")
        result = engine.evaluate(ctx)
        assert "casino_merchant" in result.triggered_rules

    def test_unknown_operator_does_not_crash(self):
        """An unknown operator should be gracefully skipped."""
        bad_rules = [
            {
                "name": "bad_rule",
                "priority": 50,
                "risk_level_if_triggered": "medium",
                "conditions": [
                    {"field": "amount", "operator": "UNKNOWN_OP", "value": 100}
                ],
            }
        ]
        engine = RuleEngine(db_rules=bad_rules)
        ctx = make_context()
        result = engine.evaluate(ctx)   # Should not raise
        assert "bad_rule" not in result.triggered_rules

    def test_in_operator(self):
        """Test the 'in' operator for list membership checks"""
        custom_rules = [
            {
                "name": "high_risk_country",
                "priority": 50,
                "risk_level_if_triggered": "high",
                "conditions": [
                    {"field": "transaction_country", "operator": "in", "value": ["IRN", "PRK", "CUB"]}
                ],
            }
        ]
        engine = RuleEngine(db_rules=custom_rules)
        ctx = make_context(transaction_country="IRN")
        result = engine.evaluate(ctx)
        assert "high_risk_country" in result.triggered_rules

    def test_not_in_operator(self):
        """Test the 'not_in' operator"""
        custom_rules = [
            {
                "name": "unsupported_currency",
                "priority": 50,
                "risk_level_if_triggered": "medium",
                "conditions": [
                    {"field": "currency", "operator": "not_in", "value": ["USD", "EUR", "GBP"]}
                ],
            }
        ]
        engine = RuleEngine(db_rules=custom_rules)
        ctx = make_context(currency="XYZ")
        result = engine.evaluate(ctx)
        assert "unsupported_currency" in result.triggered_rules
