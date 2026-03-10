"""
SentinelStream - Celery Task Queue
Handles asynchronous, non-blocking tasks:
  - Webhook delivery to merchants
  - Email alerts for high-risk transactions
  - Idempotency record cleanup
  - Periodic analytics snapshot
"""

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

import httpx
from celery import Celery
from celery.schedules import crontab
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Celery Application ──────────────────────────────────────────
celery_app = Celery(
    "sentinelstream",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.celery_app"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Reliability
    task_acks_late=True,                    # Only ack after task completes
    task_reject_on_worker_lost=True,        # Requeue if worker crashes
    task_track_started=True,
    worker_prefetch_multiplier=1,           # One task at a time per worker slot

    # Retries
    task_max_retries=5,
    task_default_retry_delay=60,            # Seconds between retries

    # Beat schedule (periodic tasks)
    beat_schedule={
        "cleanup-expired-idempotency": {
            "task": "app.tasks.celery_app.cleanup_expired_idempotency_keys",
            "schedule": crontab(minute="0", hour="*/2"),    # Every 2 hours
        },
    },
)


# ── Task: Webhook Delivery ───────────────────────────────────────

@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=30,
    name="app.tasks.deliver_webhook",
)
def deliver_webhook(
    self,
    webhook_delivery_id: str,
    webhook_url: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deliver a webhook notification to a merchant endpoint.
    Automatically retries with exponential back-off on failure.

    This task is the backbone of the Failure Recovery pillar:
    even if the merchant's server is temporarily down, the notification
    will be retried up to 5 times over ~30 minutes.
    """
    attempt = self.request.retries + 1
    logger.info(f"Delivering webhook {webhook_delivery_id} (attempt {attempt})")

    try:
        response = httpx.post(
            webhook_url,
            json=payload,
            timeout=10.0,
            headers={
                "Content-Type": "application/json",
                "X-SentinelStream-Event": "transaction.processed",
                "X-Delivery-ID": webhook_delivery_id,
            },
        )
        response.raise_for_status()

        logger.info(
            f"Webhook {webhook_delivery_id} delivered. Status: {response.status_code}"
        )
        return {"status": "delivered", "status_code": response.status_code}

    except (httpx.HTTPError, httpx.ConnectError) as exc:
        logger.warning(
            f"Webhook delivery failed (attempt {attempt}): {exc}. "
            f"Retrying in {30 * (2 ** self.request.retries)}s..."
        )
        # Exponential backoff: 30s, 60s, 120s, 240s, 480s
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


# ── Task: Fraud Alert Email ──────────────────────────────────────

@celery_app.task(
    bind=True,
    max_retries=3,
    name="app.tasks.send_fraud_alert_email",
)
def send_fraud_alert_email(
    self,
    transaction_id: str,
    user_email: str,
    user_name: str,
    amount: float,
    currency: str,
    fraud_score: float,
    risk_level: str,
    triggered_rules: list,
) -> Dict[str, Any]:
    """
    Send a fraud alert email notification to the fraud operations team.
    Triggered asynchronously when a transaction is flagged HIGH or CRITICAL.
    """
    try:
        subject = f"🚨 [{risk_level.upper()}] Fraud Alert - Transaction {transaction_id[:8]}..."

        body_html = f"""
        <html><body style="font-family: Arial, sans-serif;">
        <div style="background: #ff4444; color: white; padding: 20px; border-radius: 8px;">
            <h2>⚠️ Fraud Detection Alert</h2>
        </div>
        <div style="padding: 20px; background: #f9f9f9; margin-top: 10px; border-radius: 8px;">
            <h3>Transaction Details</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td><strong>Transaction ID:</strong></td><td>{transaction_id}</td></tr>
                <tr><td><strong>User:</strong></td><td>{user_name} ({user_email})</td></tr>
                <tr><td><strong>Amount:</strong></td><td>{currency} {amount:,.2f}</td></tr>
                <tr><td><strong>Fraud Score:</strong></td><td>{fraud_score:.2%}</td></tr>
                <tr><td><strong>Risk Level:</strong></td>
                    <td style="color: red; font-weight: bold;">{risk_level.upper()}</td></tr>
                <tr><td><strong>Triggered Rules:</strong></td>
                    <td>{", ".join(triggered_rules) if triggered_rules else "ML Model"}</td></tr>
            </table>
            <p style="margin-top: 20px;">
                <a href="http://localhost:8000/api/v1/admin/alerts/{transaction_id}"
                   style="background: #007bff; color: white; padding: 10px 20px;
                          border-radius: 5px; text-decoration: none;">
                    Review in Dashboard →
                </a>
            </p>
        </div>
        </body></html>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.ALERT_EMAIL_FROM
        msg["To"] = settings.ALERT_EMAIL_TO
        msg.attach(MIMEText(body_html, "html"))

        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            context = ssl.create_default_context()
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.ehlo()
                server.starttls(context=context)
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            logger.info(f"Fraud alert email sent for transaction {transaction_id}")
        else:
            # Log instead of sending in dev environments without SMTP configured
            logger.info(
                f"[DEV - Email not sent] Fraud Alert | TXN: {transaction_id} | "
                f"Score: {fraud_score:.2%} | Risk: {risk_level}"
            )

        return {"status": "sent", "transaction_id": transaction_id}

    except Exception as exc:
        logger.error(f"Failed to send fraud alert email: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ── Task: Cleanup Expired Idempotency Keys ───────────────────────

@celery_app.task(name="app.tasks.cleanup_expired_idempotency_keys")
def cleanup_expired_idempotency_keys() -> Dict[str, Any]:
    """
    Periodic beat task: delete expired idempotency records.
    Runs every 2 hours via Celery Beat.
    """
    import asyncio
    from sqlalchemy import delete
    from app.db.session import AsyncSessionLocal
    from app.models.models import IdempotencyRecord

    async def _cleanup():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.expires_at < datetime.now(timezone.utc)
                )
            )
            await db.commit()
            deleted = result.rowcount
            logger.info(f"Cleaned up {deleted} expired idempotency records.")
            return deleted

    loop = asyncio.new_event_loop()
    try:
        deleted = loop.run_until_complete(_cleanup())
    finally:
        loop.close()

    return {"deleted": deleted}
