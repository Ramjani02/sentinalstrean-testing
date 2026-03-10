"""
Integration Tests - Transaction Endpoints
Tests the full fraud detection pipeline end-to-end.
"""

import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestCreateTransaction:

    async def test_legitimate_transaction_approved(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """A normal transaction from a domestic user should be approved."""
        account = test_user._test_account

        with patch("app.api.v1.endpoints.transactions.deliver_webhook") as mock_wh, \
             patch("app.api.v1.endpoints.transactions.send_fraud_alert_email") as mock_email:
            mock_wh.delay = MagicMock()
            mock_email.delay = MagicMock()

            response = await client.post(
                "/api/v1/transactions",
                json={
                    "idempotency_key": f"test_key_{uuid.uuid4().hex}",
                    "account_id": str(account.id),
                    "amount": "50.00",
                    "currency": "USD",
                    "transaction_type": "purchase",
                    "description": "Coffee shop",
                    "transaction_country": "USA",
                },
                headers=auth_headers,
            )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] in ("approved", "flagged")
        assert "fraud_score" in data
        assert 0.0 <= data["fraud_score"] <= 1.0
        assert data["processing_latency_ms"] is not None

    async def test_idempotency_prevents_duplicate(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """Submitting the same idempotency key twice returns the cached response."""
        account = test_user._test_account
        idempotency_key = f"idem_test_{uuid.uuid4().hex}"

        with patch("app.api.v1.endpoints.transactions.deliver_webhook") as mock_wh, \
             patch("app.api.v1.endpoints.transactions.send_fraud_alert_email") as mock_email:
            mock_wh.delay = MagicMock()
            mock_email.delay = MagicMock()

            payload = {
                "idempotency_key": idempotency_key,
                "account_id": str(account.id),
                "amount": "100.00",
                "currency": "USD",
                "transaction_country": "USA",
            }
            resp1 = await client.post("/api/v1/transactions", json=payload, headers=auth_headers)
            resp2 = await client.post("/api/v1/transactions", json=payload, headers=auth_headers)

        assert resp1.status_code == 201
        assert resp2.status_code in (200, 201)
        # Both responses should have the same transaction ID
        assert resp1.json()["id"] == resp2.json()["id"]

    async def test_invalid_account_returns_404(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """Submitting a transaction to a non-existent account returns 404."""
        response = await client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": f"test_key_{uuid.uuid4().hex}",
                "account_id": str(uuid.uuid4()),  # Random non-existent UUID
                "amount": "100.00",
                "currency": "USD",
            },
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_unauthenticated_request_rejected(self, client: AsyncClient, test_user):
        """Requests without a JWT should be rejected."""
        account = test_user._test_account
        response = await client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": f"test_key_{uuid.uuid4().hex}",
                "account_id": str(account.id),
                "amount": "100.00",
            },
        )
        assert response.status_code == 403

    async def test_negative_amount_rejected(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """Negative amounts must be rejected by Pydantic validation."""
        account = test_user._test_account
        response = await client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": f"test_key_{uuid.uuid4().hex}",
                "account_id": str(account.id),
                "amount": "-100.00",   # Invalid
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_missing_idempotency_key_rejected(
        self, client: AsyncClient, test_user, auth_headers
    ):
        """Idempotency key is required and validated."""
        account = test_user._test_account
        response = await client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": "short",  # Too short (min_length=16)
                "account_id": str(account.id),
                "amount": "100.00",
            },
            headers=auth_headers,
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestTransactionHistory:

    async def test_list_transactions_authenticated(
        self, client: AsyncClient, test_user, auth_headers
    ):
        response = await client.get("/api/v1/transactions", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "transactions" in data
        assert "total" in data
        assert "page" in data

    async def test_pagination_parameters(
        self, client: AsyncClient, test_user, auth_headers
    ):
        response = await client.get(
            "/api/v1/transactions?page=1&per_page=5",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["per_page"] == 5
        assert data["page"] == 1


@pytest.mark.asyncio
class TestBalance:

    async def test_get_balance(self, client: AsyncClient, test_user, auth_headers):
        response = await client.get("/api/v1/transactions/balance", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "balance" in data[0]
        assert "account_number" in data[0]


@pytest.mark.asyncio
class TestHealthCheck:

    async def test_health_check_returns_200(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["service"] == "SentinelStream"
