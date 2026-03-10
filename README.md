# 🛡️ SentinelStream
### High-Throughput Real-Time Fraud Detection Engine
*Zaalima Development | Python Elite Track — Q4 Project 1*

---

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Tech Stack](#tech-stack)
3. [Quick Start (Windows)](#quick-start-windows)
4. [Project Structure](#project-structure)
5. [API Reference](#api-reference)
6. [Fraud Detection Pipeline](#fraud-detection-pipeline)
7. [ML Model](#ml-model)
8. [Running Tests](#running-tests)
9. [Load Testing](#load-testing)
10. [Week-by-Week Deliverables](#week-by-week-deliverables)

---

## Architecture Overview

```
Client / Payment Gateway
        │
        ▼
   [Nginx Proxy]  ← SSL Termination, Rate Limiting, Load Balancing
        │
        ▼
  [FastAPI App]  ← Async ASGI, JWT Auth, Idempotency Middleware
        │
   ┌────┴────────────────────────┐
   │                             │
   ▼                             ▼
[PostgreSQL]              [Redis Cache]
 Immutable Ledger          Rate Limits
 Star Schema               Idempotency
 ACID Compliant            Session Cache
        │
        ▼
[Celery Workers] ← RabbitMQ Message Broker
 Webhook Delivery
 Fraud Alert Emails
 Periodic Cleanup
```

### Fraud Detection Pipeline (target: <200ms)

```
Transaction Request
      │
      ├─→ Idempotency Check (Redis) ──[duplicate]──→ Return cached response
      │
      ├─→ Account Validation (PostgreSQL)
      │
      ├─→ Rule Engine (14 built-in + DB rules, evaluated in priority order)
      │         │
      │         └─→ [CRITICAL rule] → Immediate DECLINE
      │
      ├─→ ML Scoring (Isolation Forest, in-memory, ~5ms)
      │         │
      │         └─→ fraud_score ∈ [0.0, 1.0]
      │
      ├─→ Decision Logic (combine rule + ML signals)
      │         approve / flag / decline
      │
      ├─→ Ledger Write (PostgreSQL, async)
      │
      └─→ [Async Celery Tasks]
                ├─→ Webhook to Merchant (with retry)
                └─→ Fraud Alert Email (if HIGH/CRITICAL)
```

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Framework | **FastAPI** | High-concurrency ASGI, async endpoints |
| Database | **PostgreSQL 15** | Immutable transaction ledger (ACID) |
| ORM | **SQLAlchemy 2.0 AsyncIO** | Async database access |
| Cache | **Redis 7** | Rate limiting, idempotency, hot data |
| Task Queue | **Celery + RabbitMQ** | Async webhooks, alerts |
| ML Model | **Scikit-Learn Isolation Forest** | Anomaly/fraud detection |
| Auth | **JWT (python-jose) + bcrypt** | Stateless authentication |
| Containerization | **Docker + Docker Compose** | Environment consistency |
| Proxy | **Nginx** | SSL, rate limiting, load balancing |
| Testing | **PyTest + pytest-asyncio** | Unit + integration tests |
| Load Testing | **Locust** | Throughput & latency validation |

---

## Quick Start (Windows)

### Prerequisites
- Docker Desktop for Windows (running)
- Python 3.10+ (for running tests locally)

### 1. Clone / Navigate to the project
```cmd
cd sentinelstream
```

### 2. Start everything with one command
```cmd
start.bat
```

Or manually:
```cmd
copy .env.example .env
docker compose up --build -d
```

### 3. Access the services

| Service | URL |
|---------|-----|
| API Swagger UI | http://localhost:8000/docs |
| API ReDoc | http://localhost:8000/redoc |
| Health Check | http://localhost:8000/health |
| RabbitMQ Management | http://localhost:15672 |

### 4. Create your first user
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "password": "SecurePass1!",
    "full_name": "Your Name",
    "home_country": "USA"
  }'
```

### 5. Login and get a token
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "SecurePass1!"}'
```

### 6. Submit a transaction
```bash
curl -X POST http://localhost:8000/api/v1/transactions \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "idempotency_key": "my_unique_key_001",
    "account_id": "YOUR_ACCOUNT_ID",
    "amount": "150.00",
    "currency": "USD",
    "transaction_country": "USA",
    "description": "Coffee shop"
  }'
```

---

## Project Structure

```
sentinelstream/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── auth.py          # Register, Login, /me
│   │       │   ├── transactions.py  # Core fraud detection endpoint
│   │       │   └── admin.py         # Rules management, analytics
│   │       └── router.py
│   ├── core/
│   │   ├── config.py                # Pydantic settings
│   │   └── security.py              # JWT + bcrypt
│   ├── db/
│   │   └── session.py               # Async SQLAlchemy engine
│   ├── middleware/
│   │   └── idempotency.py           # Duplicate-charge prevention
│   ├── ml/
│   │   ├── train_model.py           # Isolation Forest training
│   │   └── fraud_scorer.py          # Real-time inference service
│   ├── models/
│   │   └── models.py                # SQLAlchemy ORM (Star Schema)
│   ├── schemas/
│   │   └── schemas.py               # Pydantic request/response models
│   ├── services/
│   │   ├── rule_engine.py           # Configurable fraud rules
│   │   └── transaction_service.py   # Orchestration layer
│   ├── tasks/
│   │   └── celery_app.py            # Async tasks (webhooks, alerts)
│   └── main.py                      # FastAPI app factory
├── tests/
│   ├── conftest.py                  # Shared fixtures
│   ├── unit/
│   │   ├── test_rule_engine.py      # Rule engine unit tests
│   │   └── test_fraud_scorer.py     # ML scorer unit tests
│   ├── integration/
│   │   ├── test_auth.py             # Auth endpoint tests
│   │   └── test_transactions.py     # Transaction pipeline tests
│   └── load_test.py                 # Locust load test
├── nginx/
│   └── nginx.conf                   # Reverse proxy config
├── docker/
│   └── Dockerfile.api
├── scripts/
│   └── init_db.sql
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
├── alembic.ini
├── .env.example
└── start.bat
```

---

## API Reference

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Create new user account |
| POST | `/api/v1/auth/login` | Get JWT tokens |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| GET | `/api/v1/auth/me` | Get current user profile |

### Transactions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/transactions` | Submit transaction (fraud detection) |
| GET | `/api/v1/transactions` | Get transaction history (paginated) |
| GET | `/api/v1/transactions/{id}` | Get single transaction |
| GET | `/api/v1/transactions/balance` | Get account balance(s) |

#### Idempotency
All `POST /transactions` requests **must** include an `Idempotency-Key` header:
```
Idempotency-Key: unique-client-generated-key-16chars-min
```

### Admin (Analyst/Admin role required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/admin/stats` | Transaction analytics dashboard |
| GET | `/api/v1/admin/alerts` | List fraud alerts |
| PUT | `/api/v1/admin/alerts/{id}/resolve` | Resolve a fraud alert |
| POST | `/api/v1/admin/rules` | Create fraud rule |
| GET | `/api/v1/admin/rules` | List fraud rules |
| PUT | `/api/v1/admin/rules/{id}` | Update fraud rule |
| DELETE | `/api/v1/admin/rules/{id}` | Deactivate fraud rule |

---

## Fraud Detection Pipeline

### Risk Levels

| Level | Fraud Score | Action |
|-------|-------------|--------|
| LOW | 0.0 – 0.49 | Auto-approved |
| MEDIUM | 0.50 – 0.64 | Flagged for review |
| HIGH | 0.65 – 0.79 | Flagged + alert sent |
| CRITICAL | 0.80 – 1.0 | Auto-declined + alert sent |

### Built-in Rules

| Rule | Condition | Risk Level |
|------|-----------|-----------|
| `velocity_attack` | >5 transactions in 1 hour | CRITICAL |
| `extreme_amount_spike` | Amount is 10x user's average | CRITICAL |
| `exceeds_balance` | Amount > account balance | CRITICAL |
| `high_amount_foreign` | Amount >$5000 AND foreign country | HIGH |
| `overnight_large_transaction` | Amount >$1000 between midnight and 4AM | MEDIUM |

---

## ML Model

**Algorithm**: Scikit-Learn `IsolationForest` (unsupervised anomaly detection)

**Features** (8 dimensions):
1. `amount` — Transaction value
2. `hour_of_day` — Hour of transaction (0-23)
3. `day_of_week` — Day (0=Monday)
4. `transactions_last_hour` — Velocity feature
5. `transactions_last_24h` — Velocity feature
6. `amount_vs_avg_ratio` — Ratio of this amount to user's 30-day average
7. `is_foreign_transaction` — 0/1 flag
8. `merchant_risk_score` — Merchant-level risk (0.0–1.0)

The model is trained on first run and cached to `ml_models/`. To retrain:
```cmd
docker compose exec api python -m app.ml.train_model
```

---

## Running Tests

### Install test dependencies locally (optional, tests also run inside Docker)
```cmd
pip install -r requirements.txt
```

### Run the full test suite
```cmd
pytest
```

### Run with coverage report
```cmd
pytest --cov=app --cov-report=html
```

### Run only unit tests
```cmd
pytest tests/unit/
```

### Run only integration tests
```cmd
pytest tests/integration/
```

---

## Load Testing

### Start the application first
```cmd
docker compose up -d
```

### Install Locust
```cmd
pip install locust
```

### Run load test (interactive UI)
```cmd
locust -f tests/load_test.py --host=http://localhost:8000
```
Then open http://localhost:8089 and configure:
- **Number of users**: 50
- **Spawn rate**: 10 users/second
- **Run time**: 60 seconds

### Week 2 Deliverable Validation
Target: **≥ 100 requests/second** at P95 latency < 200ms

---

## Week-by-Week Deliverables

### ✅ Week 1 — Planning & Architecture
- [x] Star Schema database design (Transaction fact table + dimension tables)
- [x] GitHub-ready project structure with CI/CD-ready `pytest.ini`
- [x] Full OpenAPI/Swagger documentation auto-generated
- [x] Pydantic validation on all request payloads
- [x] Alembic migration setup

### ✅ Week 2 — Core Transaction Pipeline
- [x] `POST /api/v1/transactions` endpoint
- [x] Redis caching for user profile data
- [x] SQLAlchemy AsyncIO with PostgreSQL
- [x] Idempotency middleware (prevents double-charging)
- [x] Load test script (Locust) targeting 100 req/sec

### ✅ Week 3 — Intelligence Layer
- [x] Isolation Forest ML model (trained on first run)
- [x] 5-rule built-in Rule Engine with DB-driven custom rules
- [x] Combined ML + Rule signal decision logic
- [x] Celery workers for async email alerts on high-risk flags
- [x] P95 latency target: <200ms

### ✅ Week 4 — Finalization & Deployment
- [x] Full Docker Compose stack (API + PostgreSQL + Redis + RabbitMQ + Nginx)
- [x] Nginx with SSL termination, rate limiting, load balancing
- [x] JWT authentication on all endpoints
- [x] SQL injection protection via SQLAlchemy ORM (parameterized queries)
- [x] PyTest test suite (unit + integration, 80%+ coverage target)
- [x] Security headers via Nginx config
