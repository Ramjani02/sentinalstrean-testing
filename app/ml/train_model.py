"""
SentinelStream - ML Model Training
Trains an Isolation Forest model for unsupervised fraud/anomaly detection.

The model is trained on synthetic transaction feature vectors.
In production, replace the synthetic data generator with your real
historical transaction dataset.

Run: python -m app.ml.train_model
"""

import os
import logging
import numpy as np
import pandas as pd
from pathlib import Path

import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_DIR = Path("ml_models")
MODEL_PATH = MODEL_DIR / "isolation_forest.joblib"
SCALER_PATH = MODEL_DIR / "scaler.joblib"


def generate_synthetic_data(n_samples: int = 10_000) -> pd.DataFrame:
    """
    Generate synthetic transaction feature vectors for model training.
    ~5% are injected as anomalies (fraud cases).
    """
    np.random.seed(42)
    n_fraud = int(n_samples * 0.05)
    n_legit = n_samples - n_fraud

    # ── Legitimate transactions ──────────────────────────────────
    legit = pd.DataFrame({
        "amount": np.random.lognormal(mean=4.5, sigma=1.2, size=n_legit),
        "hour_of_day": np.random.randint(8, 22, n_legit),
        "day_of_week": np.random.randint(0, 7, n_legit),
        "transactions_last_hour": np.random.poisson(lam=2, size=n_legit),
        "transactions_last_24h": np.random.poisson(lam=12, size=n_legit),
        "amount_vs_avg_ratio": np.random.normal(1.0, 0.3, n_legit).clip(0.1, 5),
        "is_foreign_transaction": np.random.binomial(1, 0.1, n_legit),
        "merchant_risk_score": np.random.beta(2, 8, n_legit),
        "label": 0,  # 0 = legitimate
    })

    # ── Fraudulent transactions (injected anomalies) ─────────────
    fraud = pd.DataFrame({
        "amount": np.random.lognormal(mean=7.5, sigma=1.5, size=n_fraud),  # Much higher
        "hour_of_day": np.random.choice([0, 1, 2, 3, 22, 23], n_fraud),   # Night hours
        "day_of_week": np.random.randint(0, 7, n_fraud),
        "transactions_last_hour": np.random.poisson(lam=8, size=n_fraud),  # Rapid succession
        "transactions_last_24h": np.random.poisson(lam=30, size=n_fraud),
        "amount_vs_avg_ratio": np.random.normal(5.0, 1.5, n_fraud).clip(2, 20),
        "is_foreign_transaction": np.random.binomial(1, 0.9, n_fraud),    # Usually foreign
        "merchant_risk_score": np.random.beta(8, 2, n_fraud),              # High-risk merchants
        "label": 1,  # 1 = fraud
    })

    return pd.concat([legit, fraud], ignore_index=True).sample(frac=1, random_state=42)


FEATURE_COLUMNS = [
    "amount",
    "hour_of_day",
    "day_of_week",
    "transactions_last_hour",
    "transactions_last_24h",
    "amount_vs_avg_ratio",
    "is_foreign_transaction",
    "merchant_risk_score",
]


def train_and_save() -> None:
    """
    Train the Isolation Forest model and persist both the scaler
    and model to disk. Safe to call multiple times (idempotent).
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Generating synthetic training data...")
    df = generate_synthetic_data(n_samples=15_000)
    X = df[FEATURE_COLUMNS].values

    logger.info("Fitting StandardScaler...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    logger.info("Training Isolation Forest (contamination=0.05)...")
    model = IsolationForest(
        n_estimators=200,
        contamination=0.05,   # Expected ~5% fraud rate
        max_samples="auto",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    # Persist artefacts
    joblib.dump(scaler, SCALER_PATH)
    joblib.dump(model, MODEL_PATH)
    logger.info(f"Model saved to {MODEL_PATH}")
    logger.info(f"Scaler saved to {SCALER_PATH}")

    # Quick sanity check on held-out anomalies
    y_true = df["label"].values
    raw_scores = model.decision_function(X_scaled)  # Higher = more normal
    # Normalise to [0,1] fraud probability (invert + scale)
    fraud_probs = 1 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())
    y_pred = (fraud_probs > 0.65).astype(int)
    logger.info("\nTraining set classification report:\n" + classification_report(y_true, y_pred))


if __name__ == "__main__":
    train_and_save()
