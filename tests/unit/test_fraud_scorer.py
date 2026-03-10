"""
Unit Tests - ML Fraud Scorer
Validates model loading, feature construction, and scoring behaviour.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.ml.fraud_scorer import FraudScoringService


@pytest.fixture
def scorer():
    """Get the singleton fraud scorer (model auto-trains if needed)."""
    return FraudScoringService()


class TestFraudScorer:

    def test_scorer_loads_without_error(self, scorer):
        assert scorer._model is not None
        assert scorer._scaler is not None

    def test_score_returns_float_in_range(self, scorer):
        fv = scorer.build_feature_vector(
            amount=100.0,
            hour_of_day=14,
            day_of_week=2,
            transactions_last_hour=1,
            transactions_last_24h=5,
            amount_vs_avg_ratio=1.0,
            is_foreign_transaction=False,
            merchant_risk_score=0.1,
        )
        score, features = scorer.score(fv)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
        assert isinstance(features, dict)
        assert len(features) == 8

    def test_legitimate_transaction_low_score(self, scorer):
        """A perfectly normal transaction should have a low fraud score."""
        fv = scorer.build_feature_vector(
            amount=50.0,
            hour_of_day=12,
            day_of_week=2,
            transactions_last_hour=1,
            transactions_last_24h=3,
            amount_vs_avg_ratio=0.9,
            is_foreign_transaction=False,
            merchant_risk_score=0.05,
        )
        score, _ = scorer.score(fv)
        assert score < 0.70, f"Expected low fraud score, got {score}"

    def test_suspicious_transaction_higher_score(self, scorer):
        """A highly anomalous transaction should score higher than normal."""
        normal_fv = scorer.build_feature_vector(
            amount=50.0, hour_of_day=12, day_of_week=2,
            transactions_last_hour=1, transactions_last_24h=3,
            amount_vs_avg_ratio=0.9, is_foreign_transaction=False,
            merchant_risk_score=0.05,
        )
        suspicious_fv = scorer.build_feature_vector(
            amount=50000.0, hour_of_day=2, day_of_week=6,
            transactions_last_hour=15, transactions_last_24h=50,
            amount_vs_avg_ratio=20.0, is_foreign_transaction=True,
            merchant_risk_score=0.95,
        )
        normal_score, _ = scorer.score(normal_fv)
        suspicious_score, _ = scorer.score(suspicious_fv)
        assert suspicious_score > normal_score

    def test_score_transaction_high_level_helper(self, scorer):
        """Test the high-level score_transaction convenience method."""
        now = datetime.now(timezone.utc)
        score, features = scorer.score_transaction(
            amount=200.0,
            created_at=now,
            transactions_last_hour=2,
            transactions_last_24h=8,
            user_avg_amount=180.0,
            user_home_country="USA",
            transaction_country="USA",
            merchant_risk_score=0.1,
        )
        assert 0.0 <= score <= 1.0
        assert "amount" in features

    def test_foreign_transaction_flag(self, scorer):
        """Foreign transactions should be flagged as such in features."""
        now = datetime.now(timezone.utc)
        score_domestic, features_domestic = scorer.score_transaction(
            amount=200.0, created_at=now, transactions_last_hour=1,
            transactions_last_24h=5, user_avg_amount=200.0,
            user_home_country="USA", transaction_country="USA",
        )
        score_foreign, features_foreign = scorer.score_transaction(
            amount=200.0, created_at=now, transactions_last_hour=1,
            transactions_last_24h=5, user_avg_amount=200.0,
            user_home_country="USA", transaction_country="CHN",
        )
        # Foreign transaction should be represented differently in features
        assert features_foreign["is_foreign_transaction"] == 1.0
        assert features_domestic["is_foreign_transaction"] == 0.0

    def test_singleton_pattern(self):
        """FraudScoringService must return the same instance (singleton)."""
        s1 = FraudScoringService()
        s2 = FraudScoringService()
        assert s1 is s2
