"""
SentinelStream - Locust Load Test
Simulates high-frequency transaction submissions to validate:
  - Minimum 100 requests/second on local infrastructure (Week 2 deliverable)
  - P95 latency < 200ms (Week 3 deliverable)

Run:
    locust -f tests/load_test.py --host=http://localhost:8000
    # Then open http://localhost:8089 for the Locust UI

Headless run:
    locust -f tests/load_test.py --host=http://localhost:8000 \
           --headless -u 50 -r 10 --run-time 60s
"""

import uuid
import random

from locust import HttpUser, between, task


# ── Test Credentials ─────────────────────────────────────────────
# Pre-register a user and paste the details + account_id here
# Or use the /api/v1/auth/register endpoint first.
TEST_EMAIL = "loadtest@sentinelstream.test"
TEST_PASSWORD = "LoadTest1!"
TEST_ACCOUNT_ID = ""   # Fill after registering


class SentinelStreamUser(HttpUser):
    """
    Simulates a bank client submitting transactions at high frequency.
    Each virtual user authenticates once, then hammers the transaction endpoint.
    """
    wait_time = between(0.05, 0.2)   # 5-200ms between requests per user

    def on_start(self):
        """Authenticate and store the JWT token for subsequent requests."""
        # Register first (ignore 409 if already exists)
        self.client.post("/api/v1/auth/register", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "full_name": "Load Test User",
            "home_country": "USA",
        })

        # Login
        response = self.client.post("/api/v1/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
        })
        if response.status_code == 200:
            self.token = response.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {self.token}"}

            # Get account ID
            balance = self.client.get(
                "/api/v1/transactions/balance",
                headers=self.headers,
            )
            if balance.status_code == 200 and balance.json():
                self.account_id = balance.json()[0]["account_id"]
            else:
                self.account_id = TEST_ACCOUNT_ID
        else:
            self.token = None
            self.headers = {}
            self.account_id = TEST_ACCOUNT_ID

    @task(10)
    def submit_normal_transaction(self):
        """Most common task: submit a normal, low-risk transaction."""
        if not self.token or not self.account_id:
            return

        self.client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": f"locust_{uuid.uuid4().hex}",
                "account_id": self.account_id,
                "amount": str(round(random.uniform(5.0, 200.0), 2)),
                "currency": "USD",
                "transaction_type": "purchase",
                "description": "Load test transaction",
                "transaction_country": "USA",
            },
            headers=self.headers,
            name="POST /transactions (normal)",
        )

    @task(2)
    def submit_suspicious_transaction(self):
        """Occasional suspicious transactions to stress-test the ML pipeline."""
        if not self.token or not self.account_id:
            return

        self.client.post(
            "/api/v1/transactions",
            json={
                "idempotency_key": f"locust_sus_{uuid.uuid4().hex}",
                "account_id": self.account_id,
                "amount": str(round(random.uniform(3000.0, 8000.0), 2)),
                "currency": "USD",
                "transaction_type": "purchase",
                "transaction_country": random.choice(["CHN", "IRN", "RUS", "USA"]),
            },
            headers=self.headers,
            name="POST /transactions (suspicious)",
        )

    @task(3)
    def get_transaction_history(self):
        """Read-heavy endpoint to simulate dashboard polling."""
        if not self.token:
            return
        self.client.get(
            "/api/v1/transactions?page=1&per_page=10",
            headers=self.headers,
            name="GET /transactions",
        )

    @task(1)
    def check_balance(self):
        """Balance check endpoint."""
        if not self.token:
            return
        self.client.get(
            "/api/v1/transactions/balance",
            headers=self.headers,
            name="GET /balance",
        )

    @task(1)
    def health_check(self):
        """Health probe — simulates load balancer checks."""
        self.client.get("/health", name="GET /health")
