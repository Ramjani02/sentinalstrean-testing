"""
SentinelStream - ML Inference Service
Loads the pre-trained Isolation Forest model and provides
sub-10ms fraud scoring for each transaction.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Tuple

import joblib
import numpy as np

from app.core.config import settings
from app.ml.train_model import FEATURE_COLUMNS, train_and_save

logger = logging.getLogger(__name__)


class FraudScoringService:
    """
    Singleton service that holds the loaded model and scaler in memory.
    Avoids re-loading from disk on every request.

    Usage:
        scorer = FraudScoringService()
        score, features = scorer.score(transaction_features)
    """

    _instance = None
    _model = None
    _scaler = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_models()
        return cls._instance

    def _load_models(self) -> None:
        """Load serialised model artefacts from disk. Auto-trains if missing."""
        model_path = Path(settings.ML_MODEL_PATH)
        scaler_path = Path(settings.ML_SCALER_PATH)

        if not model_path.exists() or not scaler_path.exists():
            logger.warning("ML model not found — training now. This may take ~30s.")
            train_and_save()

        self._scaler = joblib.load(scaler_path)
        self._model = joblib.load(model_path)
        logger.info("Fraud scoring model loaded successfully.")

    def build_feature_vector(
        self,
        amount: float,
        hour_of_day: int,
        day_of_week: int,
        transactions_last_hour: int,
        transactions_last_24h: int,
        amount_vs_avg_ratio: float,
        is_foreign_transaction: bool,
        merchant_risk_score: float,
    ) -> np.ndarray:
        """
        Assemble the feature vector in the exact order the model was trained on.
        """
        return np.array([[
            amount,
            hour_of_day,
            day_of_week,
            transactions_last_hour,
            transactions_last_24h,
            amount_vs_avg_ratio,
            float(is_foreign_transaction),
            merchant_risk_score,
        ]])

    def score(self, feature_vector: np.ndarray) -> Tuple[float, Dict[str, Any]]:
        """
        Run inference and return a normalised fraud score in [0, 1].

        Returns:
            (fraud_score, feature_dict)
            - fraud_score: 0.0 = definitely legitimate, 1.0 = highly suspicious
        """
        X_scaled = self._scaler.transform(feature_vector)
        raw_score = self._model.decision_function(X_scaled)[0]

        # Normalise: Isolation Forest returns negative scores for anomalies
        # We invert and clip to [0,1] so higher = more fraudulent
        # Using a fixed empirical range for stability in production
        NORMAL_UPPER = 0.15
        ANOMALY_LOWER = -0.25
        clipped = float(np.clip(raw_score, ANOMALY_LOWER, NORMAL_UPPER))
        fraud_score = 1.0 - (clipped - ANOMALY_LOWER) / (NORMAL_UPPER - ANOMALY_LOWER)
        fraud_score = float(np.clip(fraud_score, 0.0, 1.0))

        feature_dict = dict(zip(FEATURE_COLUMNS, feature_vector[0].tolist()))

        return round(fraud_score, 4), feature_dict

    def score_transaction(
        self,
        amount: float,
        created_at,
        transactions_last_hour: int,
        transactions_last_24h: int,
        user_avg_amount: float,
        user_home_country: str,
        transaction_country: str,
        merchant_risk_score: float = 0.1,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        High-level helper: accepts raw transaction fields and returns a fraud score.
        """
        hour_of_day = created_at.hour if created_at else 12
        day_of_week = created_at.weekday() if created_at else 0
        amount_vs_avg_ratio = (amount / user_avg_amount) if user_avg_amount > 0 else 1.0
        is_foreign = (
            transaction_country is not None
            and user_home_country is not None
            and transaction_country.upper() != user_home_country.upper()
        )

        fv = self.build_feature_vector(
            amount=float(amount),
            hour_of_day=hour_of_day,
            day_of_week=day_of_week,
            transactions_last_hour=transactions_last_hour,
            transactions_last_24h=transactions_last_24h,
            amount_vs_avg_ratio=float(amount_vs_avg_ratio),
            is_foreign_transaction=is_foreign,
            merchant_risk_score=float(merchant_risk_score),
        )
        return self.score(fv)


# Module-level singleton
fraud_scorer = FraudScoringService()
