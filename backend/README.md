<div align="center">

# ⚡ StreamPulse

### Real-Time Event Processing & Analytics Platform

<em>Ingest → Validate → Deduplicate → Queue → Process → Retry → Dead-Letter → Analyze → Stream Live</em>

<br/>

![Python](https://img.shields.io/badge/Python-3.11%20|%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.153-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14%2B-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x%20async-D71F00?style=for-the-badge)
![Alembic](https://img.shields.io/badge/Alembic-Migrations-6BA81E?style=for-the-badge)

![Argon2id](https://img.shields.io/badge/Passwords-Argon2id-8A2BE2?style=for-the-badge)
![JWT](https://img.shields.io/badge/Auth-JWT%20%2B%20RBAC-000000?style=for-the-badge&logo=jsonwebtokens&logoColor=white)
![SSE](https://img.shields.io/badge/Live%20Updates-SSE-FF6B35?style=for-the-badge)
![Tests](https://img.shields.io/badge/Tests-119%20passing-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)
![No Docker](https://img.shields.io/badge/Docker-not%20required-2496ED?style=for-the-badge&logo=docker&logoColor=white)

<br/>

**A modular-monolith backend that receives events from other applications, stores them durably, processes them asynchronously, and tells you honestly what happened to every one.**
One FastAPI app. PostgreSQL as the single source of truth. No Docker, WSL, Kafka, or Redis required.

<br/>

[✨ Features](#-features) • [🏗️ Architecture](#️-architecture) • [🚀 Quick Start](#-quick-start-windows) • [🌐 API Reference](#-api-reference) • [🧠 Design Decisions](#-design-decisions-worth-knowing-for-an-interview)

</div>

<br/>

---

## 📖 Table of Contents

- [About](#-about)
- [Features](#-features)
- [Architecture](#️-architecture)
- [Event State Machine](#-event-state-machine)
- [Retry, Dead-Letter & Recovery Design](#️-retry-dead-letter--recovery-design)
- [Tech Stack](#️-tech-stack)
- [Project Structure](#-project-structure)
- [Quick Start (Windows)](#-quick-start-windows)
- [Keys & Secrets — What You Must Create](#-keys--secrets--what-you-must-create)
- [Environment Variables](#️-environment-variables)
- [API Reference](#-api-reference)
- [API Examples](#-api-examples)
- [Roles & Permissions](#-roles--permissions)
- [Database Schema](#️-database-schema)
- [Security](#-security-features)
- [Delivery Guarantees](#-delivery-guarantees)
- [Analytics Metric Definitions](#-analytics-metric-definitions)
- [Testing](#-testing)
- [Load Testing & Measured Results](#-load-testing--measured-results)
- [Frontend Integration Notes](#-frontend-integration-notes)
- [Troubleshooting](#-troubleshooting-windows--postgresql)
- [Known Limitations](#️-known-limitations)
- [Design Decisions](#-design-decisions-worth-knowing-for-an-interview)
- [Roadmap](#️-roadmap)

---

## 📌 About

Real systems don't just *receive* data — they have to accept it quickly, never lose it, never process it twice by accident, survive crashes, and show operators exactly what went wrong.

**StreamPulse demonstrates that reality** with a realistic event-pipeline backend. Applications (e-commerce orders, payments, user activity, application errors, service-health pings) send events to a REST API. StreamPulse validates and stores each one in PostgreSQL, processes it in the background, retries transient failures with backoff, quarantines hopeless ones in a dead-letter table, and exposes SQL-powered analytics plus a live Server-Sent-Events stream for dashboards.

> Producer app → `POST /events` (API key) → **validated, de-duplicated, committed to PostgreSQL** → `202 Accepted` → bounded in-process queue → async workers → `PROCESSED` *or* retry with backoff → `DEAD_LETTER` → operators inspect, **reprocess** or resolve → every admin action lands in the **audit log**.

<table>
<tr>
<td width="50%">

**🛡️ Honest by construction**
`202 Accepted` never means "processed". The API returns `QUEUED`/`RECEIVED` at accept time and only the worker can set `PROCESSED`. The README documents what is *not* guaranteed (exactly-once, ordering, multi-instance) rather than implying it.

</td>
<td width="50%">

**🗄️ PostgreSQL is the source of truth**
The in-memory `asyncio.Queue` is only a dispatch hint. If the process dies, a sweeper and startup recovery re-dispatch everything from the database. Losing the queue loses nothing.

</td>
</tr>
<tr>
<td width="50%">

**🔁 Two kinds of idempotency, kept separate**
Event-level dedup (`event_id` is a DB unique constraint with atomic `INSERT … ON CONFLICT`) *and* optional request-level `Idempotency-Key` replay. Concurrent duplicates cannot create two rows — tested with 25 simultaneous submissions.

</td>
<td width="50%">

**🧍 Security enforced on the server**
Every privileged endpoint checks permissions in a FastAPI dependency. No public sign-up. API keys and JWTs are never stored or logged in plaintext. The UI hiding a button is never the only protection.

</td>
</tr>
</table>

---

## ✨ Features

| Feature | Description | Status |
|---|---|:---:|
| 📥 Event Ingestion | Single + bounded batch endpoints, per-item partial success, `202` accepted ≠ processed | ✅ |
| ✅ Validation | Required fields, schema versions, tz-aware timestamps, size & nesting limits, event-type-specific payload rules | ✅ |
| 🔁 Deduplication | DB unique constraint + atomic upsert; safe under concurrent submission; duplicate counter | ✅ |
| 🪪 Request Idempotency | Optional `Idempotency-Key` header → stored response replayed (24h) | ✅ |
| 🔑 Producer API Keys | 256-bit random, HMAC-hashed, shown once, scopes, expiry, revoke, tenant lock | ✅ |
| 🚦 Rate Limiting & Quotas | Per-key sliding window (429 + `Retry-After`) and daily event quota | ✅ |
| 📏 Size Limits | Request body (413, even for chunked uploads), per-event payload, batch size | ✅ |
| ⚙️ Async Workers | N configurable workers on a bounded queue, atomic claim, handler timeout | ✅ |
| ♻️ Retries & Backoff | Exponential backoff, retryable vs non-retryable errors, bounded attempts | ✅ |
| 💀 Dead Letters | Exhausted/permanent failures stored, inspectable, resolvable, reprocessable | ✅ |
| 🧯 Crash Recovery | Startup recovery + sweeper redispatch from PostgreSQL; interrupted attempts recorded | ✅ |
| 🛑 Graceful Shutdown | In-flight work gets a grace period, stragglers marked `INTERRUPTED` and resumed next start | ✅ |
| 🌊 Back-pressure | Full queue → `503 QUEUE_FULL` + `Retry-After` *before* persisting; memory stays bounded | ✅ |
| 📊 Analytics | 8 endpoints, pure PostgreSQL aggregates, percentiles, gap-filled time series | ✅ |
| 📡 Live Updates | Server-Sent Events with heartbeat, bounded per-client buffers, ticket auth for `EventSource` | ✅ |
| 🔐 Auth | JWT, Argon2id, login lockout + IP throttle, logout revocation, password change invalidates tokens | ✅ |
| 🧑‍🤝‍🧑 RBAC | 4 roles × 12 permissions, custom roles, last-admin protection, payload redaction for viewers | ✅ |
| 📜 Audit Log | Admin & security actions recorded; secrets scrubbed from details | ✅ |
| 🏥 Health Checks | `/health`, `/health/live`, `/health/ready` reporting real DB/worker/queue state | ✅ |
| 🪵 Observability | Structured JSON logs, request IDs on every request/response/log line, uniform error envelope | ✅ |
| 🧮 Migrations | Alembic (async); CI-style `alembic check` test fails if models and migration drift | ✅ |
| 🧪 119 Automated Tests | Real PostgreSQL, isolated `_test` database, concurrency + recovery + shutdown tests | ✅ |
| 📈 Load Test Script | Repeatable HTTPX script with seed, duplicates, back-pressure handling, processing throughput | ✅ |
| 🐳 Docker | Deliberately **not** used in this version — documented upgrade path only | ⏭️ |

---

## 🏗️ Architecture

A **modular monolith**: one FastAPI process that also runs the background workers (started and stopped by the FastAPI lifespan). Clean module boundaries make later extraction straightforward.

```
 Producer apps ── X-API-Key ──►  POST /events · POST /events/batch
                                         │
                       auth → rate-limit → idempotency replay → validate → tenant check
                                         │          (503 QUEUE_FULL if the queue is saturated)
                                         ▼
                 INSERT … ON CONFLICT (event_id)  →  COMMIT       ◄──── PostgreSQL = source of truth
                                         │
                                         ▼  202 Accepted  (NOT "processed")
                           ┌───────────────────────────┐
                           │  asyncio.Queue (bounded)   │  in-memory dispatch hint only
                           └─────────────┬─────────────┘
                                         ▼
            ┌───────────── N async workers ──────────────┐        ┌───────────── sweeper ─────────────┐
            │ atomic claim (conditional UPDATE)           │        │ every few seconds + at startup:    │
            │ → run handler (timeout) → record attempt    │        │ re-dispatch RECEIVED / QUEUED /    │
            │ → PROCESSED | RETRYING | DEAD_LETTER        │        │ due-RETRYING events from Postgres  │
            └──────────────┬──────────────────────────────┘        └────────────────────────────────────┘
                           │ state change
                           ▼
                  EventBroker (in-process pub/sub, bounded buffers)
                           │
                           ▼
                 GET /events/stream  (Server-Sent Events)

 Dashboard users ── JWT ──► /auth · /users · /roles · /permissions · /api-keys
                            /events · /analytics (SQL aggregates) · /admin/audit-logs
```

Request pipeline middleware (outermost → innermost): **CORS → request-id + access log → body-size limit → routes**.

---

## 🔄 Event State Machine

Every transition is a *conditional* `UPDATE … WHERE status IN (…)`, so two workers can never process the same event at the same time.

```
   POST /events  ──►  RECEIVED  ───────────────►  QUEUED
        (persisted before 202)    (enqueued)          │
                                                      ▼
                                                 PROCESSING ──────────────► PROCESSED ✔
                                                      │
                          ┌───────────────────────────┤
                          ▼ retryable error / timeout │ non-retryable error
                      RETRYING                        │ or retries exhausted
          (next_retry_at = now + backoff)             ▼
                          │                      FAILED ──► DEAD_LETTER
                          └──► PROCESSING …                      │
                                                                  ▼
             operator: POST /events/{id}/reprocess  ──► RECEIVED (retry_count reset, history kept)
             operator: POST /events/dead-letters/{id}/resolve ──► dead letter marked RESOLVED
```

> `FAILED` is a transient step *inside one transaction* — the event is written directly as `DEAD_LETTER`. The value exists in the schema and analytics for completeness.

---

## ♻️ Retry, Dead-Letter & Recovery Design

```
 handler raises ProcessingError / times out
          │
          ▼
   retry_count < EVENT_MAX_RETRIES ?
      │ yes                                   │ no, or NonRetryableProcessingError
      ▼                                       ▼
   status = RETRYING                       status = DEAD_LETTER  + dead_letter_events row (OPEN)
   next_retry_at = now + min(base·2^(n-1), max)       │
      │                                                ▼
      ▼ (sweeper picks it up once due)         operators: reprocess  OR  resolve (discard)
   PROCESSING …
```

* Total attempts = `1 + EVENT_MAX_RETRIES` (default 4). Backoff: 2 s, 4 s, 8 s … capped at 60 s.
* Each attempt is a `processing_attempts` row (`RUNNING → SUCCESS | FAILED | INTERRUPTED`) with duration and a **sanitized, length-capped** error (bearer tokens, API keys, DSNs and `password=…` patterns are scrubbed; no stack traces stored).
* **Crash recovery** — on startup, events stuck in `PROCESSING` are re-scheduled (attempt marked `INTERRUPTED`), and everything pending in PostgreSQL is re-dispatched. The same sweeper also repairs the "persisted but queue was full" window at runtime.
* **Graceful shutdown** — workers stop taking work, in-flight handlers get `EVENT_SHUTDOWN_GRACE_SECONDS`, anything still running is cancelled and recorded as `INTERRUPTED` (shielded write), then resumes on the next start.

---

## 🛠️ Tech Stack

<table>
<tr><td><b>Framework</b></td><td>FastAPI 0.153 · Uvicorn · Pydantic v2 · pydantic-settings</td></tr>
<tr><td><b>Database</b></td><td>PostgreSQL (JSONB payloads) · SQLAlchemy 2.x async · asyncpg · bounded connection pool</td></tr>
<tr><td><b>Migrations</b></td><td>Alembic (async env, deterministic constraint names, drift check in the test suite)</td></tr>
<tr><td><b>Async Processing</b></td><td><code>asyncio.Queue</code> + worker tasks + sweeper, managed by the FastAPI lifespan (no external broker)</td></tr>
<tr><td><b>Live Updates</b></td><td>Server-Sent Events over <code>StreamingResponse</code>, in-process broker with bounded buffers</td></tr>
<tr><td><b>Auth & Crypto</b></td><td>PyJWT (HS256) · Argon2id (argon2-cffi) · HMAC-SHA256 API-key hashing with a server-side pepper</td></tr>
<tr><td><b>Analytics</b></td><td>SQL aggregates with <code>FILTER</code>, <code>date_trunc</code>, <code>percentile_cont</code></td></tr>
<tr><td><b>Testing</b></td><td>pytest · pytest-asyncio (session loop) · HTTPX ASGI transport · real PostgreSQL</td></tr>
<tr><td><b>Load Testing</b></td><td>HTTPX async script (seeded, repeatable)</td></tr>
</table>

---

## 📂 Project Structure

<details>
<summary><b>Click to expand full directory tree</b></summary>

```
StreamPulse/
├── app/
│   ├── main.py                    app factory + lifespan (engine, RBAC seed, workers, maintenance)
│   ├── config.py                  pydantic-settings, secret validation
│   ├── database.py                async engine/session factory, Base, naming conventions
│   ├── dependencies.py            DB session, JWT auth, permission checks, API-key auth + rate limit
│   ├── core/
│   │   ├── security.py            Argon2id, JWT, API-key generation & hashing
│   │   ├── permissions.py         permission catalogue + default roles (single source of truth)
│   │   ├── exceptions.py          AppError hierarchy + uniform error responses
│   │   ├── logging.py             JSON logging, request-id context
│   │   └── rate_limit.py          sliding-window limiter
│   ├── models/                    users · roles · permissions · api_keys · events · attempts · dead letters · audit · auth_support
│   ├── schemas/                   Pydantic request/response models
│   ├── services/
│   │   ├── auth_service.py        login/lockout, token validation, logout, password change
│   │   ├── user_service.py        users, activation, last-admin protection
│   │   ├── role_service.py        roles & role↔permission assignment
│   │   ├── api_key_service.py     API-key lifecycle + authentication
│   │   ├── event_service.py       validation, dedup insert, queries, reprocess, dead-letter resolve
│   │   ├── processing_service.py  handler registry + atomic state transitions + recovery queries
│   │   ├── analytics_service.py   SQL aggregations
│   │   ├── idempotency_service.py Idempotency-Key storage/replay
│   │   ├── audit_service.py       audit writes (secret scrubbing) + queries
│   │   ├── event_broker.py        SSE pub/sub + frame formatting
│   │   └── rbac_seed.py           idempotent permission/role seeding
│   ├── workers/
│   │   ├── event_queue.py         bounded queue with in-flight de-dup
│   │   └── event_worker.py        worker manager: workers, sweeper, recovery, shutdown
│   ├── middleware/                request_id.py (+access log) · body_limit.py
│   └── api/v1/                    auth · users · roles · permissions · api_keys · events · analytics · admin · health · router
├── alembic/                       async env + versions/ (initial schema)
├── scripts/
│   ├── setup_database.sql         creates role + databases (run once as postgres)
│   ├── generate_secrets.py        SECRET_KEY / API_KEY_PEPPER generator
│   ├── bootstrap_admin.py         create the first administrator securely
│   └── load_test.py               repeatable load test
├── tests/                         119 tests (see Testing)
├── data/  logs/                   created automatically
├── .env.example · requirements.txt · requirements-dev.txt · pytest.ini · alembic.ini · .gitignore
└── README.md
```

</details>

---

## 🚀 Quick Start (Windows)

> No Docker, WSL, Kafka or Redis needed — just Python and a locally installed PostgreSQL.

### 1️⃣ Prerequisites
* **Python 3.11 or 3.12** (python.org, tick *Add to PATH*) — check with `py --version`
* **PostgreSQL 14+** installed directly from <https://www.postgresql.org/download/windows/> (port `5432`; remember the `postgres` superuser password)
* Make `psql` available (adjust the version number):
  ```powershell
  $env:Path += ";C:\Program Files\PostgreSQL\16\bin"
  psql --version
  ```

### 2️⃣ Virtual environment
```powershell
cd path\to\StreamPulse
py -m venv .venv
.\.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements-dev.txt # runtime + tests (requirements.txt = runtime only)
```

### 3️⃣ Create the database & application role
1. Open `scripts\setup_database.sql` and replace `CHANGE_ME_STRONG_PASSWORD`.
2. Run it as the superuser:
   ```powershell
   psql -U postgres -h localhost -f scripts/setup_database.sql
   ```
3. Verify:
   ```powershell
   psql -U streampulse_app -h localhost -d streampulse_db -c "select current_user, current_database();"
   ```

### 4️⃣ Configure `.env`
```powershell
copy .env.example .env
python -m scripts.generate_secrets      # paste both values into .env
notepad .env                            # set the DB password inside DATABASE_URL
```

### 5️⃣ Migrate & create the first admin
```powershell
alembic upgrade head
python -m scripts.bootstrap_admin --username admin --email admin@example.com   # prompts for a hidden password
```

### 6️⃣ Run
```powershell
uvicorn app.main:app --reload
```
📍 API docs: <http://127.0.0.1:8000/docs> (click **Authorize**) · Health: <http://127.0.0.1:8000/health>

<details>
<summary><b>Useful Alembic commands</b></summary>

```powershell
alembic current                                    # applied revision
alembic history                                    # all revisions
alembic check                                      # fail if models differ from migrations
alembic revision --autogenerate -m "describe"      # after changing a model — review the file!
alembic downgrade -1                               # roll back one revision
```
The app never drops or recreates tables on startup.
</details>

---

## 🔐 Keys & Secrets — What You Must Create

| # | Item | What it is | Where it lives | How to create |
|---|------|-----------|----------------|---------------|
| 1 | **PostgreSQL superuser password** | Admin of your local PostgreSQL | Set at install | You choose it. Used **once** for the setup SQL; the app never uses it. |
| 2 | **`streampulse_app` role + password** | Least-privilege, non-superuser DB role | `DATABASE_URL` in `.env` | `scripts/setup_database.sql` |
| 3 | **Databases** `streampulse_db`, `streampulse_test` | App data / isolated test data | PostgreSQL | same SQL file |
| 4 | **`SECRET_KEY`** | Signs JWT access tokens. A leak lets anyone forge a login. | `.env` | `python -m scripts.generate_secrets` — changing it logs everyone out |
| 5 | **`API_KEY_PEPPER`** | HMAC key mixed into API-key hashes so a stolen DB can't verify keys | `.env` | `python -m scripts.generate_secrets` — **changing it invalidates every API key** |
| 6 | **First admin account** | The only way in initially (there is **no** public sign-up) | `users` table | `python -m scripts.bootstrap_admin` (refuses if an admin already exists) |
| 7 | **Producer API keys** | One per producing application/tenant | Shown **once**; only a hash is stored | `POST /api/v1/api-keys` as an admin |

**Rules:** never commit `.env`; use different secrets per environment; in `APP_ENV=production` the app refuses to start if a secret looks like a placeholder; a lost API key can't be recovered — revoke it and create a new one.

---

## ⚙️ Environment Variables

<details>
<summary><b>Click to expand full <code>.env</code> reference</b></summary>

```env
APP_NAME=StreamPulse
APP_ENV=development            # development | testing | production
API_V1_PREFIX=/api/v1
LOG_LEVEL=INFO
LOG_JSON=true                  # false = readable logs while developing
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# PostgreSQL (URL-encode special characters: @ -> %40)
DATABASE_URL=postgresql+asyncpg://streampulse_app:YOUR_DB_PASSWORD@localhost:5432/streampulse_db
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10

# python -m scripts.generate_secrets   (each >= 32 chars)
SECRET_KEY=GENERATE_ME
API_KEY_PEPPER=GENERATE_ME

ACCESS_TOKEN_EXPIRE_MINUTES=30
LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15

# Ingestion limits
MAX_BATCH_SIZE=100
MAX_PAYLOAD_BYTES=16384
MAX_REQUEST_BODY_BYTES=2097152
DEFAULT_RATE_LIMIT_PER_MINUTE=600
SUPPORTED_SCHEMA_VERSIONS=1.0

# Queue / workers (keep small on a laptop)
EVENT_QUEUE_MAXSIZE=1000
EVENT_WORKER_CONCURRENCY=2
EVENT_MAX_RETRIES=3
EVENT_RETRY_BASE_DELAY_SECONDS=2
EVENT_RETRY_MAX_DELAY_SECONDS=60
EVENT_PROCESSING_TIMEOUT_SECONDS=30
EVENT_SWEEP_INTERVAL_SECONDS=5
```

Other tunables (defaults in `app/config.py`): `SSE_HEARTBEAT_SECONDS` (15), `SSE_MAX_CLIENTS` (100), `IDEMPOTENCY_TTL_HOURS` (24), `MAX_EVENT_AGE_DAYS` (365), `AUTO_SEED_RBAC` (true), `EVENT_SHUTDOWN_GRACE_SECONDS` (10).
</details>

---

## 🌐 API Reference

All paths are under `/api/v1` unless noted. **JWT** = `Authorization: Bearer …` + the listed permission · **KEY** = `X-API-Key: …`.

<details open>
<summary><b>🔑 Authentication</b></summary>
<br/>

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | none | username **or email** + password → access token (throttled, lockout) |
| `POST` | `/auth/token` | none | OAuth2 form login (powers Swagger's *Authorize* button) |
| `POST` | `/auth/logout` | JWT | revokes the current token |
| `GET` | `/auth/me` | JWT | profile + effective permissions |
| `POST` | `/auth/change-password` | JWT | invalidates all older tokens, returns a fresh one |

</details>

<details open>
<summary><b>📥 Event Ingestion (API-key authenticated)</b></summary>
<br/>

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/events` | KEY (`events.ingest`) | one event → `202` accepted · `200` duplicate · `413/422/403/429/503` |
| `POST` | `/events/batch` | KEY | bounded batch → `202` with `accepted / duplicates / rejected` counts + per-item results |

Optional header: `Idempotency-Key` (replays the stored response).
</details>

<details open>
<summary><b>🔎 Events, Live Stream & Operator Actions</b></summary>
<br/>

| Method | Endpoint | Permission | Description |
|---|---|---|---|
| `GET` | `/events` | `events.read` | filters: `status` (multi), `event_type`, `source`, `customer_id`, `event_id`, `from`, `to`; `limit`/`offset` |
| `GET` | `/events/{id}` | `events.read` | detail + attempt history + dead-letter history (payload needs `events.read_payload`) |
| `POST` | `/events/{id}/reprocess` | `events.reprocess` | re-queue a `FAILED`/`DEAD_LETTER` event (else `409`) |
| `POST` | `/events/dead-letters/{id}/resolve` | `events.reprocess` | mark a dead letter resolved/discarded |
| `POST` | `/events/stream-ticket` | `events.read` | one-time 30 s ticket for `EventSource` |
| `GET` | `/events/stream` | `events.read` | Server-Sent Events (`?ticket=…` or Bearer header) |

</details>

<details open>
<summary><b>📊 Analytics</b></summary>
<br/>

All require `analytics.read` and accept `from`/`to` (default last 24 h) plus `event_type`, `source`, `customer_id`.

| Endpoint | Returns |
|---|---|
| `GET /analytics/overview` | totals, processed/failed/pending/processing, duplicates, retries, open dead letters, events/min, success & failure rate, avg latency |
| `GET /analytics/events-by-type` | counts per type (`limit`) |
| `GET /analytics/events-over-time` | `interval=minute\|hour\|day`, gap-filled buckets with processed/failed |
| `GET /analytics/failure-rates` | `group_by=event_type\|source\|customer_id`, worst first |
| `GET /analytics/processing-latency` | avg/min/max/p50/p95/p99, optional `group_by` |
| `GET /analytics/top-sources` | busiest sources (`limit`) |
| `GET /analytics/queue-status` | queue size/capacity/utilization, workers alive, saturation, DB counts per status |
| `GET /analytics/dead-letters` | paginated, filter by `resolution_status`, `event_type`, `source` |

</details>

<details>
<summary><b>👥 Users, Roles, Permissions, API Keys, Audit</b></summary>
<br/>

| Method | Endpoint | Permission |
|---|---|---|
| `GET` / `POST` | `/users` · `/users/{id}` (`GET`,`PATCH`) | `users.read` / `users.manage` |
| `POST` | `/users/{id}/activate` · `/deactivate` · `PUT /users/{id}/roles` | `users.manage` |
| `GET` / `POST` | `/roles` · `/roles/{id}` (`GET`,`PATCH`,`DELETE`) | `users.read` or `roles.manage` / `roles.manage` |
| `PUT` | `/roles/{id}/permissions` · `GET /permissions` | `permissions.manage` |
| `POST` / `GET` | `/api-keys` · `/api-keys/{id}` (`GET`,`PATCH`) · `POST /api-keys/{id}/revoke` | `api_keys.manage` / `api_keys.read` |
| `GET` | `/admin/audit-logs` (`action`, `actor_user_id`, `success`, `from`, `to`) | `audit_logs.read` |

</details>

<details>
<summary><b>🏥 Health (root, no prefix)</b></summary>
<br/>

| Endpoint | Behavior |
|---|---|
| `GET /health/live` | always `200` while the process runs |
| `GET /health/ready` | `200` only if PostgreSQL answers **and** all workers + sweeper are alive; otherwise `503` |
| `GET /health` | full detail: database, workers, queue (size/capacity/utilization/saturated), uptime — `503` if not ready |

Responses never contain credentials, DSNs or stack traces.
</details>

<div align="center">

**44 endpoints** · list endpoints return `{items, total, limit, offset}` · every error uses the same envelope (below)

</div>

**Status codes you'll meet:** `200` duplicate/OK · `201` created · `202` accepted · `401` missing/invalid/expired/revoked credential · `403` permission, scope or tenant violation · `404` · `409` conflict · `413` body/payload/batch too large · `422` validation · `429` rate limit / quota / lockout (`Retry-After`) · `503` queue full (`Retry-After`) or dependency down.

```json
{ "error": { "code": "RATE_LIMITED", "message": "Rate limit exceeded", "request_id": "9f2c…", "details": null } }
```

---

## 💡 API Examples

<details>
<summary><b>Log in & create a producer API key (PowerShell)</b></summary>

```powershell
$base  = "http://127.0.0.1:8000/api/v1"
$login = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType "application/json" `
           -Body (@{ username = "admin"; password = "YOUR_PASSWORD" } | ConvertTo-Json)
$auth  = @{ Authorization = "Bearer $($login.access_token)" }

$key = Invoke-RestMethod -Method Post -Uri "$base/api-keys" -Headers $auth -ContentType "application/json" `
         -Body (@{ name = "checkout-service"; customer_id = "acme"; rate_limit_per_minute = 600 } | ConvertTo-Json)
$key.key          # sp_ab12cd34_…   <-- shown ONCE, store it now
$apiKey = @{ "X-API-Key" = $key.key }
```
`customer_id` locks the key to a tenant: events for any other customer get `403 CUSTOMER_MISMATCH`.
</details>

<details>
<summary><b>Send one event</b></summary>

```powershell
$event = @{
  event_id = "order-1001"; event_type = "order.created"; source = "checkout-service"; customer_id = "acme"
  schema_version = "1.0"; timestamp = (Get-Date).ToUniversalTime().ToString("o")
  payload = @{ order_id = "1001"; amount = 59.90; currency = "USD" }; metadata = @{ region = "eu" }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "$base/events" -Headers $apiKey -ContentType "application/json" -Body $event
```
```json
{ "status": "accepted", "id": "0b6c…", "event_id": "order-1001", "processing_status": "QUEUED" }
```
`202` = **accepted for processing, not processed**. Re-sending the same `event_id` returns `200` with `"status": "duplicate"`.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/events -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"event_id":"order-1002","event_type":"order.created","source":"checkout","timestamp":"2026-10-21T10:00:00Z","payload":{"order_id":"1002","amount":10,"currency":"USD"}}'
```
</details>

<details>
<summary><b>Send a batch (partial success is normal)</b></summary>

`POST /events/batch` with `{"events": [ … ]}` (max `MAX_BATCH_SIZE`):
```json
{ "accepted": 2, "duplicates": 1, "rejected": 1,
  "results": [
    {"index":0,"event_id":"b-1","status":"accepted","id":"…"},
    {"index":1,"event_id":"b-2","status":"rejected","code":"invalid_payload","message":"payload.amount is required; …"},
    {"index":2,"event_id":"order-1001","status":"duplicate","id":"…","code":"duplicate_event"},
    {"index":3,"event_id":"b-4","status":"accepted","id":"…"} ] }
```
One bad event never rejects the others. Rejection codes: `validation_error`, `unsupported_schema_version`, `invalid_timestamp`, `invalid_payload`, `payload_too_large`, `customer_mismatch`, `duplicate_in_batch`.
</details>

<details>
<summary><b>HTTP idempotency vs. event de-duplication — two different things</b></summary>

* **Event-level dedup** — `event_id` is unique in PostgreSQL: *"this event already exists."* A retry gets `200 duplicate`.
* **Request-level idempotency** — send `Idempotency-Key: <unique string>`: *"this exact HTTP request was already handled,"* so the **stored response is replayed** (`Idempotent-Replayed: true`). Reusing the key with a different body → `409 IDEMPOTENCY_KEY_REUSED`.
</details>

<details>
<summary><b>Inspect failures, reprocess, query analytics</b></summary>

```powershell
Invoke-RestMethod "$base/events?status=DEAD_LETTER&limit=20" -Headers $auth
Invoke-RestMethod "$base/events/<id>" -Headers $auth                          # attempts + dead-letter history
Invoke-RestMethod -Method Post "$base/events/<id>/reprocess" -Headers $auth
Invoke-RestMethod "$base/analytics/overview" -Headers $auth
Invoke-RestMethod "$base/analytics/events-over-time?interval=minute&from=2026-10-21T10:00:00Z" -Headers $auth
Invoke-RestMethod "$base/admin/audit-logs?action=event.reprocessed" -Headers $auth
```
</details>

<details>
<summary><b>Validation rules per event</b></summary>

Required: `event_id` (unique, `[A-Za-z0-9._:-]`), `event_type` (dotted lowercase), `source`, `timestamp` (timezone-aware, ≤ 5 min in the future, ≤ 365 days old), `payload` (object). Optional: `customer_id`, `schema_version` (default `1.0`; must be in `SUPPORTED_SCHEMA_VERSIONS`), `metadata`. Payload/metadata ≤ `MAX_PAYLOAD_BYTES`, nesting ≤ 10, no NUL characters.

| Event type | Required payload |
|---|---|
| `order.created` | `order_id`, `amount` ≥ 0, `currency` (3 letters) |
| `payment.succeeded`, `payment.failed` | `payment_id`, `amount` ≥ 0, `currency` |
| `user.activity` | `user_id`, `action` |
| `app.error` | `service`, `message` |
| `service.health` | `service`, `status` ∈ `up`, `degraded`, `down` |
| *any other type* | any JSON object |
</details>

---

## 🧑‍🤝‍🧑 Roles & Permissions

Enforced **server-side on every endpoint** and re-read from the database on every request, so changes apply immediately.

| Permission | ADMIN | OPERATOR | ANALYST | VIEWER |
|---|:-:|:-:|:-:|:-:|
| `events.read` | ✅ | ✅ | ✅ | ✅ |
| `events.read_payload` *(otherwise payload/metadata are redacted)* | ✅ | ✅ | ✅ | ❌ |
| `events.reprocess` | ✅ | ✅ | ❌ | ❌ |
| `analytics.read` *(also the live stream)* | ✅ | ✅ | ✅ | ✅ |
| `users.read` · `users.manage` · `roles.manage` · `permissions.manage` | ✅ | ❌ | ❌ | ❌ |
| `api_keys.read` · `api_keys.manage` · `audit_logs.read` | ✅ | ❌ | ❌ | ❌ |
| `events.ingest` | assignable; producers use **API-key scopes** | | | |

**Safety rails:** system roles can't be deleted · ADMIN always holds every permission · you can't deactivate yourself or remove the last active admin · a deactivated user's token stops working immediately.

---

## 🗃️ Database Schema

<details>
<summary><b>Click to expand (12 tables, created by one Alembic migration)</b></summary>

```
users ─────────< user_roles >───────── roles ─────< role_permissions >───── permissions
  │ username*, email*, password_hash (Argon2id)
  │ is_active, is_verified, last_login_at
  │ failed_login_attempts, locked_until, token_version
  │
  ├──< revoked_tokens   (jti, expires_at)                     logout denylist, purged after expiry
  └──< api_keys         (key_prefix*, key_hash, scopes[], customer_id, expires_at, revoked_at,
        │                 rate_limit_per_minute, daily_event_quota, last_used_at)
        ├──< idempotency_records (api_key_id + key unique, request_hash, stored response)
        └──< events      (event_id* UNIQUE, event_type, source, customer_id, schema_version,
              │           occurred_at, payload JSONB, event_metadata JSONB, status, retry_count,
              │           duplicate_count, received_at, processing_started_at, completed_at,
              │           processing_duration_ms, last_error, next_retry_at)
              ├──< processing_attempts  (event_id + attempt_number unique, outcome, duration_ms, error)
              └──< dead_letter_events   (failure_reason, retry_count, resolution_status, resolved_by…)

audit_logs  (actor, action, target, success, ip_address, request_id, details JSONB)      * = unique
```

**Indexes exist for a reason** (each is commented in `app/models/event.py`): `received_at` for time ranges; `(status, received_at)` for sweeps; `(event_type | source | customer_id, received_at)` for filtered lists & group-bys; `(api_key_id, received_at)` for quota counting; a *partial* index on `next_retry_at WHERE status='RETRYING'` for due-retry scans.
</details>

---

## 🔒 Security Features

- 🔑 **Passwords:** Argon2id, hashed off the event loop; min 12 chars with letter + digit; no plaintext anywhere
- 🪙 **JWT:** HS256 with `exp/iat/jti/iss`; `alg=none` and tampered tokens rejected; logout revokes the `jti`; password change bumps a `token_version` that kills every older token
- 🧱 **Brute-force protection:** per-account lockout (5 failures → 15 min) *and* per-IP throttle; identical responses for unknown user vs wrong password; dummy hash verification equalises timing
- 🗝️ **API keys:** 256-bit `secrets` randomness, HMAC-SHA256 + server pepper, constant-time compare, shown once, never logged or audited; scopes, expiry, instant revocation
- 🏢 **Tenant isolation (ingestion):** a key bound to `customer_id` can only write that tenant; unscoped events are stamped with it
- 🛡️ **RBAC:** permission dependencies on every protected route; custom roles; payload redaction by permission; last-admin and self-lockout protection
- 🚦 **Abuse limits:** per-key rate limit, daily quota, body-size limit (also for chunked uploads), batch-size limit, per-event payload limit, nesting depth limit
- 🧾 **Audit trail:** user/role/permission/API-key/reprocess/login events with request ID and IP; secrets scrubbed recursively
- 🧼 **Error hygiene:** validation errors never echo submitted values (e.g. passwords); stored processing errors are scrubbed of tokens/keys/DSNs; 500s return a generic envelope
- 🌐 **CORS** allow-list from `CORS_ORIGINS` (off if empty); `/docs` disabled when `APP_ENV=production`; production refuses placeholder secrets
- 🔐 **Least-privilege DB role**, never the superuser; secrets only in `.env` (git-ignored)

---

## 📦 Delivery Guarantees

**What is guaranteed (single instance):**
- ✅ A `202` means the event is **already committed to PostgreSQL**.
- ✅ **No duplicate rows** for an `event_id`, even under concurrent submission (DB constraint + atomic upsert).
- ✅ **At-least-once processing** — after a crash or shutdown, pending and interrupted events are re-dispatched, so **handlers must be idempotent**.
- ✅ **No two workers** process the same event simultaneously (atomic claim).
- ✅ **Bounded memory** — fixed queue capacity; overload becomes `503 + Retry-After`, not growth or silent loss.
- ✅ Full **attempt history** per event, even across manual reprocessing.

**What is NOT guaranteed:** exactly-once delivery · global ordering · distributed fault tolerance · multi-instance safety (queue, SSE broker, rate limiter and stream tickets are per-process).

<details>
<summary><b>Writing your own business logic (handlers)</b></summary>

The registry is created in the lifespan in `app/main.py` (`app.state.handlers = HandlerRegistry()`). Register handlers right after that line, before the workers start:

```python
from app.services.processing_service import EventContext, NonRetryableProcessingError, ProcessingError

async def handle_order(ctx: EventContext) -> None:
    ...  # raise ProcessingError (retried) or NonRetryableProcessingError (straight to dead letter)

app.state.handlers.register("order.created", handle_order)
```
The default handler accepts events unchanged — it is the extension point. `ctx` carries `event_id`, `event_type`, `source`, `customer_id`, `payload`, `metadata`, `attempt_number`.
</details>

---

## 📈 Analytics Metric Definitions

Window = `[from, to)` on `received_at` (default: last 24 h). Everything is computed with PostgreSQL aggregates — nothing is loaded into Python memory.

| Metric | Definition |
|---|---|
| `total_received` | events received in the window |
| `processed` / `failed` / `pending` / `processing` | status = `PROCESSED` / (`FAILED`,`DEAD_LETTER`) / (`RECEIVED`,`QUEUED`,`RETRYING`) / `PROCESSING` |
| `success_rate`, `failure_rate` | `processed/(processed+failed)` and `failed/(processed+failed)`; **`null` when nothing has finished** (no division by zero) |
| `events_per_minute` | `total_received ÷ window length in minutes` |
| `duplicate_submissions` | sum of `duplicate_count` (re-submissions of an existing `event_id`) |
| `retries_total` | sum of `retry_count` |
| latency `avg`, `p50/p95/p99` | over `PROCESSED` events via `percentile_cont`; `null` with no samples |
| `events-over-time` | minute/hour/day buckets, **gap-filled with zeros**, max 2000 buckets |

---

## 🧪 Testing

Tests run against a **separate database** and **refuse to run** unless its name ends in `_test`. By default it is derived from `DATABASE_URL` (`streampulse_db` → `streampulse_test`); override with `TEST_DATABASE_URL`. The schema is built with the **real Alembic migrations** on every run.

```powershell
pytest                              # everything (~2 min)
pytest tests/test_ingestion.py -q   # one file
pytest -k "concurrent or recovery" -v
```

| Test file | What it proves |
|---|---|
| `test_health_and_errors` | live/ready/health reflect real state (DB down → 503), error envelope, request-id, no leaked input, graceful shutdown |
| `test_security_units` | Argon2id, JWT tamper/expiry/`alg=none`, API-key hashing, rate limiter, secret scrubbing, settings guards |
| `test_auth` | login/me, lockout, IP throttle, logout revocation, password change, deactivation takes effect instantly |
| `test_rbac` | role × endpoint matrix, last-admin protection, custom roles, system-role protection, payload redaction |
| `test_api_keys` | shown once, never stored/logged, revoke, expire, scope, rate limit, daily quota, audit trail |
| `test_ingestion` | validation, schema versions, batches, size limits, **25 concurrent duplicates → 1 row**, tenant isolation, idempotency |
| `test_processing` | retries, dead letters, non-retryable, timeout, reprocess + authorization, **queue-full**, **restart recovery**, **mid-flight shutdown**, exactly-one-claim race, no double processing |
| `test_analytics` | hand-computed metrics on a seeded dataset, empty data, filters, pagination, percentiles, gap-filling |
| `test_sse` | frame format, heartbeat, bounded buffers/overflow, disconnect cleanup, ticket auth, end-to-end stream through the real ASGI app |
| `test_migrations` | models ↔ migration in sync (`alembic check`), downgrade/upgrade cycle |
| `test_cors` | allowed origin preflight, unknown origin rejected |

---

## 🚀 Load Testing & Measured Results

```powershell
# Create an API key with a high rate limit first (default is 600 requests/min per key), then:
python -m scripts.load_test --api-key sp_xxx --events 5000 --concurrency 20 --batch-size 50 `
   --duplicate-ratio 0.05 --seed 42 --username admin --password "YOUR_PASSWORD"
```
It is **repeatable** (`--seed`), honours `429/503` + `Retry-After`, retries dropped keep-alive connections, and reports request throughput, latency percentiles, accepted/duplicate/rejected counts, back-pressure counts and — with admin credentials — peak queue utilisation and end-to-end processing throughput.

**What I actually measured** (Linux sandbox with **1 vCPU shared by uvicorn, PostgreSQL *and* the load generator**; your PC will differ — run it yourself and trust your own numbers):

| Scenario | Result |
|---|---|
| Batch endpoint (50 events/request, 10 clients, 2 workers, WARNING logs) | ingest **≈ 630–880 events/s**; request p50 ≈ 48–94 ms, p95 ≈ 170–410 ms |
| Overload behaviour | queue saturated → **20–37 requests got `503` + `Retry-After`**, all succeeded on retry; **0 failed events** |
| End-to-end processing, 2 workers vs 8 workers | **≈ 115 events/s** vs **≈ 122 events/s** — no meaningful gain |
| Single-event endpoint (20 clients, 5 % duplicates, INFO access logs) | **≈ 64–80 req/s**; duplicates correctly returned as `200 duplicate` |
| Handler time (trivial default handler) | p50 ≈ 0.35 ms, p99 ≈ 6–7 ms — cost is database round-trips, not the handler |

> **Interpretation:** with a trivial handler, throughput is bounded by one Python process plus database round-trips on one core. Extra workers didn't help, and during the run `top` showed uvicorn as the busiest process (I did not profile further). The bounded queue and `503` back-pressure behaved as designed under overload.
>
> **Scaling honestly:** PostgreSQL + one in-process queue is **not** a distributed pipeline and will not match a message broker with multiple worker processes. That is exactly the [future upgrade path](#️-roadmap).

---

## 🎨 Frontend Integration Notes

- **CORS:** list your frontend origin(s) in `CORS_ORIGINS`. No cookies are used (`allow_credentials` is off); send the token in the `Authorization` header.
- **Auth flow:** `POST /auth/login` → keep `access_token` → send `Authorization: Bearer …`. Tokens last 30 min; on `401` with `TOKEN_EXPIRED` / `TOKEN_REVOKED` / `INVALID_TOKEN` send the user to login. *There are no refresh tokens.*
- **Role-aware UI:** call `GET /auth/me` → `permissions: [...]` and hide what the user can't do. The server enforces everything regardless.
- **Live updates:** `EventSource` can't set headers, so:
  1. `POST /events/stream-ticket` (Bearer auth) → `{ ticket, expires_in_seconds }`
  2. `new EventSource(`${base}/api/v1/events/stream?ticket=${ticket}`)` — ticket is single-use, valid ~30 s.

  Event names: `connected`, `event.received`, `event.processing`, `event.processed`, `event.retrying`, `event.dead_lettered`, `event.reprocess_requested`, `overflow` (your buffer overflowed → refetch via REST). Heartbeat comment every 15 s. Messages carry ids/status only — **never payloads**. The stream is **not durable**: after reconnecting, reload from `GET /events` / analytics.
- **Charts:** `events-over-time` is already gap-filled; rates can be `null` (render "–").
- **Pagination:** `{ items, total, limit, offset }`. **Errors:** always `{ error: { code, message, request_id, details } }` — show `message`, log `request_id`.
- **Redaction:** for `VIEWER` users `payload`/`metadata` are `null` with `payload_redacted: true`.

---

## 🩺 Troubleshooting (Windows / PostgreSQL)

| Symptom | Likely cause / fix |
|---|---|
| `psql` is not recognized | Add `C:\Program Files\PostgreSQL\<ver>\bin` to PATH |
| `password authentication failed for user "streampulse_app"` | `.env` password ≠ the one in `setup_database.sql`; URL-encode special characters. Reset: `psql -U postgres -c "ALTER ROLE streampulse_app PASSWORD 'new'"` |
| App exits with *"PostgreSQL is unreachable"* / `Connection refused … 5432` | Start the *postgresql-x64-NN* service in `services.msc`; check `Get-NetTCPConnection -LocalPort 5432` |
| `database "streampulse_db" does not exist` | Run `scripts/setup_database.sql` |
| `permission denied for schema public` | Re-run the `GRANT ALL ON SCHEMA public …` lines as `postgres` (PostgreSQL 15+ tightened `public`) |
| `ValidationError … SECRET_KEY … at least 32 characters` | `python -m scripts.generate_secrets`, paste into `.env` |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `pip install` fails building a package | Use 64-bit Python 3.11/3.12 and upgrade pip |
| Tests: *"Refusing to run: the test database name must end with '_test'"* | Create `streampulse_test` (setup SQL) or set `TEST_DATABASE_URL` |
| `503 QUEUE_FULL` under load | Expected back-pressure: honour `Retry-After`, raise `EVENT_WORKER_CONCURRENCY`/`EVENT_QUEUE_MAXSIZE`, or slow the producers |
| Port 8000 busy | `uvicorn app.main:app --port 8001` |
| Behind a reverse proxy every client has the same IP | start uvicorn with `--proxy-headers --forwarded-allow-ips <proxy-ip>` |

---

## ⚠️ Known Limitations

- **Single instance only.** Queue, SSE broker, rate limiter and stream tickets are in-process. Do **not** use `uvicorn --workers N`. (Atomic claims keep correctness if you try, but startup recovery in one instance can re-schedule another's in-flight events.)
- In-memory rate limits reset on restart and aren't shared across instances; the daily quota is counted from the database.
- No refresh tokens, MFA, email verification (`is_verified` is stored but not enforced) or password-reset emails.
- Tenant scoping covers **ingestion** (API key ↔ `customer_id`). Dashboard users see all tenants' events according to their role.
- The default event handler is a no-op accept; real business logic is registered by you.
- Event duplicates are detected by `event_id` only — payloads are not compared.
- Verified on Linux (Python 3.12, PostgreSQL 16). The Windows steps use only cross-platform libraries, but treat your first Windows run as the final verification.

---

## 🧠 Design Decisions Worth Knowing for an Interview

> 💡 **PostgreSQL is the source of truth; the queue is only a hint.** An `asyncio.Queue` is not durable, so correctness never depends on it. Every accepted event is committed first; a sweeper and startup recovery re-dispatch from the database. Losing the process loses no events.

> 💡 **`202 Accepted` is deliberately not "success".** The API reports `QUEUED`/`RECEIVED` and only a worker can write `PROCESSED`, so producers and dashboards can't mistake "received" for "done".

> 💡 **Deduplication lives in the database, not in memory.** `INSERT … ON CONFLICT (event_id) DO UPDATE SET duplicate_count = duplicate_count + 1 RETURNING (xmax = 0)` is atomic and tells new rows from duplicates in one statement — correct under concurrency without locks or in-memory sets.

> 💡 **Claiming work is a conditional `UPDATE`.** `UPDATE … WHERE status IN (…) RETURNING` means only one worker wins an event, with no distributed lock. The same pattern guards success/failure transitions.

> 💡 **Back-pressure instead of buffering.** When the bounded queue is full, ingestion answers `503 + Retry-After` *before* persisting, so memory is bounded and nothing is silently dropped.

> 💡 **Retries only where they can help.** Handler errors and timeouts back off exponentially; an explicit `NonRetryableProcessingError` goes straight to the dead-letter table. Dead letters are first-class data (status, resolver, notes), not a log line.

> 💡 **At-least-once, stated plainly.** Exactly-once isn't claimed. Interrupted attempts are recorded as `INTERRUPTED` and retried, which is why handlers must be idempotent — and why the README says so.

> 💡 **A real bug the tests caught:** after an `UPDATE`, the database-generated `updated_at` was expired and async SQLAlchemy can't lazy-load it (`MissingGreenlet`) — fixed with `eager_defaults`. Another: audit rows for new objects had no target id because UUIDs are assigned at flush. Both were found by running the real stack against PostgreSQL, not by reading code.

> 💡 **Even chunked uploads can't bypass the body limit.** FastAPI converts exceptions raised while reading a body into a 400, so the middleware answers `413` itself and swallows the app's later response.

> 💡 **SSE needs its own auth story.** Browsers' `EventSource` can't send an `Authorization` header and query-string JWTs leak into logs, so the stream accepts a short-lived, single-use ticket instead.

> 💡 **Modular monolith first.** One deployable process with strict module boundaries (routes → services → models; workers separate) keeps the system testable and runnable on a laptop, while keeping the seams — `dispatch()`, `processing_service`, `analytics_service`, the limiter and the broker — ready for extraction.

---

## 🗺️ Roadmap

- [x] FastAPI + PostgreSQL + async SQLAlchemy modular monolith
- [x] Event ingestion (single + batch) with validation, schema versions and size limits
- [x] Atomic deduplication + request-level idempotency keys
- [x] Async workers, retries with backoff, dead letters, crash recovery, graceful shutdown
- [x] Back-pressure with a bounded queue
- [x] JWT auth + Argon2id + lockout/throttling + RBAC + audit log
- [x] Producer API keys with scopes, expiry, rate limits, quotas and tenant lock
- [x] SQL analytics (8 endpoints) and SSE live updates
- [x] Structured logging, request IDs, health/readiness checks
- [x] Alembic migrations with a drift-check test
- [x] 119 automated tests + repeatable load-test script
- [ ] Frontend dashboard (built separately)
- [ ] Dockerfile + Docker Compose
- [ ] Kafka / Redpanda in place of the in-process queue
- [ ] Redis for distributed rate limiting, stream tickets and SSE fan-out
- [ ] Dedicated worker processes (with lease/heartbeat-based recovery)
- [ ] Prometheus / Grafana / OpenTelemetry
- [ ] Table partitioning + retention jobs for the `events` table
- [ ] CI/CD (pytest + `alembic check` against a service container)
- [ ] Refresh tokens, MFA, per-tenant dashboard isolation (row-level security)

> **Future upgrade seams already in the code:** ingestion calls `EventWorkerManager.dispatch(ids)`; processing only touches `processing_service`; analytics is pure SQL in `analytics_service`; the rate limiter and broker are small replaceable classes.

---

<div align="center">

### 📄 License

No formal license file is included yet — treat this as a portfolio/educational project unless a `LICENSE` is added.

<br/>

**Built with FastAPI · PostgreSQL · SQLAlchemy · Alembic · Argon2 · Server-Sent Events**

⭐ *If this project helped you understand event-driven backend design, consider giving it a star.*

</div>
