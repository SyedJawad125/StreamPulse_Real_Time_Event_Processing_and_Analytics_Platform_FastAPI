# StreamPulse — Real-Time Event Processing & Analytics Platform (Backend)

A FastAPI + PostgreSQL backend that **receives events from other applications, validates and stores them,
processes them asynchronously, retries failures, dead-letters what cannot be processed, de-duplicates
events, and serves analytics + live updates** — all runnable on a normal Windows PC **without Docker, WSL,
Kafka, or Redis**.

This repository contains the **backend only** (REST API + SSE). The frontend is built separately; see
[Frontend integration notes](#12-frontend-integration-notes).

**Status (verified in my build environment, Python 3.12 + PostgreSQL 16 on Linux):**
119 automated tests pass against a real PostgreSQL database, the Alembic migration applies/rolls back/is in
sync with the models, and a live uvicorn server was exercised over real HTTP (login → API key → ingestion →
SSE → load test). I could not run it on Windows itself; the Windows steps below use only cross-platform
libraries (asyncpg, argon2-cffi wheels exist for Windows) but treat the first Windows run as the
final verification and use the troubleshooting section if something differs.

---

## Table of contents
1. [Architecture](#1-architecture)
2. [What you must create: database, keys & secrets](#2-what-you-must-create-database-keys--secrets)
3. [Windows setup (step by step)](#3-windows-setup-step-by-step)
4. [Running the API](#4-running-the-api)
5. [Using the API (examples)](#5-using-the-api-examples)
6. [Endpoint reference](#6-endpoint-reference)
7. [Roles & permissions](#7-roles--permissions)
8. [Event pipeline & delivery guarantees](#8-event-pipeline--delivery-guarantees)
9. [Analytics metric definitions](#9-analytics-metric-definitions)
10. [Tests](#10-tests)
11. [Load testing & measured results](#11-load-testing--measured-results)
12. [Frontend integration notes](#12-frontend-integration-notes)
13. [Configuration reference](#13-configuration-reference)
14. [Troubleshooting (Windows / PostgreSQL)](#14-troubleshooting-windows--postgresql)
15. [Known limitations](#15-known-limitations)
16. [Future upgrade path (not implemented)](#16-future-upgrade-path-not-implemented)

---

## 1. Architecture

Modular monolith: **one FastAPI process** that also runs the background workers (started/stopped by the
FastAPI lifespan).

```
 Producer apps ──X-API-Key──►  POST /events, /events/batch ─┐
                                                            ▼
                                   validate → INSERT … ON CONFLICT (dedupe) → COMMIT   ◄── PostgreSQL = source of truth
                                                            │ 202 Accepted (NOT "processed")
                                                            ▼
                                   asyncio.Queue (bounded, in-memory dispatch hint)
                                                            │
                         ┌──────────────── N async workers ─┴──────────┐   sweeper: re-dispatches RECEIVED/QUEUED/
                         │ claim (atomic UPDATE) → handler → result    │   due-RETRYING events from PostgreSQL
                         └──────┬───────────────────────┬──────────────┘   (this is also the crash-recovery path)
                          PROCESSED            RETRYING (backoff) → … → DEAD_LETTER
                                   │
                  EventBroker (SSE) ──► GET /events/stream     Analytics ──► SQL aggregations
 Dashboard users ──JWT──► /auth, /users, /roles, /api-keys, /events, /analytics, /admin
```

```
app/
├── main.py              app factory + lifespan (engine, RBAC seed, workers, maintenance)
├── config.py            pydantic-settings (.env)
├── database.py          engine/session factory, Base, naming conventions
├── dependencies.py      DB session, JWT auth, permission checks, API-key auth + rate limit
├── core/                security (Argon2id, JWT, API keys), logging, exceptions, permissions, rate limiter
├── models/              SQLAlchemy models (users, roles, permissions, api_keys, events, attempts, dead letters, audit…)
├── schemas/             Pydantic request/response models
├── services/            business logic (auth, users, roles, api keys, events, processing, analytics, audit, SSE broker)
├── workers/             event_queue.py (bounded queue) + event_worker.py (workers, sweeper, recovery, shutdown)
├── middleware/          request-id + access log, request body size limit
└── api/v1/              thin routers
alembic/                 migrations   scripts/   bootstrap admin, secrets, DB SQL, load test   tests/   119 tests
```

State machine (every transition is a conditional `UPDATE`, so two workers can never process one event at once):

```
RECEIVED → QUEUED → PROCESSING → PROCESSED
                        └─► RETRYING ─► PROCESSING …   (exponential backoff)
                        └─► FAILED → DEAD_LETTER       (retries exhausted, or a non-retryable error)
DEAD_LETTER ─(manual reprocess)─► RECEIVED
```
(`FAILED` is an in-transaction step: the event is written straight to `DEAD_LETTER`; `FAILED` exists in the
schema and in analytics for completeness.)

---

## 2. What you must create: database, keys & secrets

You asked for guidance on the important values. Here is **everything that must exist and why**:

| # | Item | What it is | Where it lives | How to create |
|---|------|-----------|----------------|---------------|
| 1 | **PostgreSQL superuser password** | Admin of your local PostgreSQL | Set during PostgreSQL install | You choose it; only used to run `setup_database.sql` once. **The app never uses it.** |
| 2 | **DB application role** `streampulse_app` + password | Least-privilege role the app connects as | `DATABASE_URL` in `.env` | `scripts/setup_database.sql` (edit the password first) |
| 3 | **Databases** `streampulse_db`, `streampulse_test` | App data / isolated test data | PostgreSQL | same SQL file |
| 4 | **`SECRET_KEY`** | Signs dashboard JWT access tokens. Leak ⇒ anyone can forge a login. | `.env` | `python -m scripts.generate_secrets`. Changing it logs everyone out. |
| 5 | **`API_KEY_PEPPER`** | Secret mixed (HMAC) into API-key hashes, so a stolen DB alone can't be used to verify keys | `.env` | `python -m scripts.generate_secrets`. **Changing it invalidates every existing API key.** |
| 6 | **First admin account** | The only way to get into the system initially | `users` table | `python -m scripts.bootstrap_admin` (interactive, hidden password). There is **no** public sign-up endpoint. |
| 7 | **API keys for producers** | One per producing application/tenant | shown **once** at creation; only a hash is stored | `POST /api/v1/api-keys` as an admin |

Rules of thumb: never commit `.env`; use different `SECRET_KEY`/`API_KEY_PEPPER`/passwords per environment;
in `APP_ENV=production` the app refuses to start if a secret still looks like a placeholder; API keys are
shown only once — if lost, revoke and create a new one.

---

## 3. Windows setup (step by step)

### 3.1 Prerequisites
* **Python 3.11 or 3.12** from python.org (tick "Add python.exe to PATH"). Check: `py --version`
* **PostgreSQL 14+** (installed directly, no Docker): download the Windows installer from
  <https://www.postgresql.org/download/windows/> (EDB). Keep the defaults (port **5432**), set and remember
  the `postgres` superuser password. You don't need Stack Builder.
* Add PostgreSQL's `bin` folder to PATH so `psql` works, e.g. (adjust the version number):
  ```powershell
  $env:Path += ";C:\Program Files\PostgreSQL\16\bin"        # this window only
  psql --version
  ```

### 3.2 Project + virtual environment
```powershell
cd path\to\StreamPulse
py -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements-dev.txt   # runtime + test dependencies (use requirements.txt for runtime only)
```

### 3.3 Create the database and application role
1. Open `scripts\setup_database.sql` and **replace `CHANGE_ME_STRONG_PASSWORD`** with a strong password.
2. Run it as the superuser (you'll be asked for the `postgres` password):
   ```powershell
   psql -U postgres -h localhost -f scripts/setup_database.sql
   ```
3. Verify the new role can log in:
   ```powershell
   psql -U streampulse_app -h localhost -d streampulse_db -c "select current_user, current_database();"
   ```

### 3.4 Configure `.env`
```powershell
copy .env.example .env
python -m scripts.generate_secrets      # copy both lines into .env
notepad .env                            # set DATABASE_URL password + the two secrets
```
If your DB password contains special characters, URL-encode them in `DATABASE_URL` (`@`→`%40`, `#`→`%23`, `/`→`%2F`).

### 3.5 Apply migrations
```powershell
alembic upgrade head          # create/upgrade all tables
alembic current               # show the applied revision
alembic history               # list revisions
alembic check                 # fails if models differ from the migration (useful before commits)
# after changing a model:     alembic revision --autogenerate -m "describe change"   then review the file, then upgrade
```
The app never drops or recreates tables on startup.

### 3.6 Create the first administrator
```powershell
python -m scripts.bootstrap_admin --username admin --email admin@example.com
```
You'll be prompted for a password (≥12 chars, letters + digits). The command also seeds roles/permissions and
**refuses to run if an active admin already exists** (override with `--allow-additional`).

---

## 4. Running the API
```powershell
uvicorn app.main:app --reload                 # development (auto-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000   # no reload
```
* Interactive docs (non-production): <http://127.0.0.1:8000/docs> — click **Authorize**, log in with the admin
  username/password to try protected endpoints.
* Health: <http://127.0.0.1:8000/health>, `/health/live`, `/health/ready`.
* In production (`APP_ENV=production`) `/docs`, `/redoc` and `/openapi.json` are disabled.
* Run it as a **single process** (do not use `--workers N`; see [limitations](#15-known-limitations)).

---

## 5. Using the API (examples)

### 5.1 Log in (dashboard user) — PowerShell
```powershell
$base = "http://127.0.0.1:8000/api/v1"
$login = Invoke-RestMethod -Method Post -Uri "$base/auth/login" -ContentType "application/json" `
  -Body (@{ username = "admin"; password = "YOUR_PASSWORD" } | ConvertTo-Json)
$auth = @{ Authorization = "Bearer $($login.access_token)" }
```
Response: `{"access_token":"…","token_type":"bearer","expires_at":"…","user":{…}}`

### 5.2 Create an API key for a producer application
```powershell
$key = Invoke-RestMethod -Method Post -Uri "$base/api-keys" -Headers $auth -ContentType "application/json" `
  -Body (@{ name = "checkout-service"; customer_id = "acme"; rate_limit_per_minute = 600; daily_event_quota = 100000 } | ConvertTo-Json)
$key.key        # sp_ab12cd34_…  <-- shown ONCE. Store it now.
$apiKey = @{ "X-API-Key" = $key.key }
```
`customer_id` (optional) locks the key to one tenant: events for any other customer are rejected with 403.

### 5.3 Send one event
```powershell
$event = @{
  event_id = "order-1001"; event_type = "order.created"; source = "checkout-service"; customer_id = "acme"
  schema_version = "1.0"; timestamp = (Get-Date).ToUniversalTime().ToString("o")
  payload = @{ order_id = "1001"; amount = 59.90; currency = "USD" }
  metadata = @{ region = "eu" }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "$base/events" -Headers $apiKey -ContentType "application/json" -Body $event
```
```json
{ "status": "accepted", "id": "0b6c…", "event_id": "order-1001", "processing_status": "QUEUED" }
```
`202` means **accepted for processing, not processed**. Sending the same `event_id` again returns **`200`** with
`"status": "duplicate"`. curl equivalent:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/events -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"event_id":"order-1002","event_type":"order.created","source":"checkout","timestamp":"2026-10-21T10:00:00Z","payload":{"order_id":"1002","amount":10,"currency":"USD"}}'
```

### 5.4 Send a batch (partial success is normal)
`POST /events/batch` with `{"events":[ … up to MAX_BATCH_SIZE … ]}` →
```json
{ "accepted": 2, "duplicates": 1, "rejected": 1,
  "results": [
    {"index":0,"event_id":"b-1","status":"accepted","id":"…"},
    {"index":1,"event_id":"b-2","status":"rejected","code":"invalid_payload","message":"payload.amount is required; …"},
    {"index":2,"event_id":"order-1001","status":"duplicate","id":"…","code":"duplicate_event"},
    {"index":3,"event_id":"b-4","status":"accepted","id":"…"} ] }
```
One bad event never rejects the others. Item rejection codes: `validation_error`, `unsupported_schema_version`,
`invalid_timestamp`, `invalid_payload`, `payload_too_large`, `customer_mismatch`, `duplicate_in_batch`.

### 5.5 HTTP idempotency vs event de-duplication (two different things)
* **Event-level dedup** — unique `event_id` enforced by PostgreSQL. "This *event* already exists." A retry gets `200 duplicate`.
* **Request-level idempotency** — optional `Idempotency-Key: <unique string>` header. "This exact *HTTP request* was
  already handled": the stored response is **replayed** (header `Idempotent-Replayed: true`). Reusing the key with a
  different body → `409 IDEMPOTENCY_KEY_REUSED`. Records are kept for `IDEMPOTENCY_TTL_HOURS` (24h).

### 5.6 Inspect, filter, reprocess
```powershell
Invoke-RestMethod "$base/events?status=DEAD_LETTER&limit=20" -Headers $auth
Invoke-RestMethod "$base/events/<id>" -Headers $auth                         # attempts + dead-letter history
Invoke-RestMethod -Method Post "$base/events/<id>/reprocess" -Headers $auth  # FAILED/DEAD_LETTER only
Invoke-RestMethod "$base/analytics/overview" -Headers $auth
Invoke-RestMethod "$base/analytics/events-over-time?interval=minute&from=2026-10-21T10:00:00Z" -Headers $auth
```

### 5.7 Error format (all endpoints)
```json
{ "error": { "code": "RATE_LIMITED", "message": "Rate limit exceeded", "request_id": "9f2c…", "details": null } }
```
Send `X-Request-ID` to correlate; the server echoes it (or generates one) in the response header and logs.

Status codes you will meet: `200` duplicate/OK · `201` created · `202` accepted · `401` missing/invalid/expired/revoked
credential · `403` forbidden (permission, scope, tenant) · `404` · `409` conflict · `413` body/payload/batch too large ·
`422` validation · `429` rate limit / daily quota / login lockout (`Retry-After`) · `503` queue full (`Retry-After`) or dependency down.

---

## 6. Endpoint reference

All under `/api/v1` unless noted. **Auth**: `JWT` = `Authorization: Bearer …` plus the listed permission; `KEY` = `X-API-Key`.

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /health`, `/health/live`, `/health/ready` (root, no prefix) | none | Component health / liveness / readiness (503 if DB or workers are down) |
| `POST /auth/login` · `POST /auth/token` (form, for Swagger) | none | Get access token (throttled, lockout) |
| `POST /auth/logout` · `GET /auth/me` · `POST /auth/change-password` | JWT | Revoke token · profile+permissions · change password (invalidates old tokens) |
| `GET/POST /users` · `GET/PATCH /users/{id}` | `users.read` / `users.manage` | User management |
| `POST /users/{id}/activate` · `/deactivate` · `PUT /users/{id}/roles` | `users.manage` | Account state & role assignment |
| `GET/POST /roles` · `GET/PATCH/DELETE /roles/{id}` | `users.read`·`roles.manage` | Roles (system roles protected) |
| `PUT /roles/{id}/permissions` · `GET /permissions` | `permissions.manage` | Role ↔ permission assignment |
| `POST/GET /api-keys` · `GET/PATCH /api-keys/{id}` · `POST /api-keys/{id}/revoke` | `api_keys.manage` / `api_keys.read` | Producer API keys |
| `POST /events` · `POST /events/batch` | **KEY** (`events.ingest` scope) | Ingest |
| `GET /events` · `GET /events/{id}` | `events.read` (`events.read_payload` to see payloads) | Query events |
| `POST /events/{id}/reprocess` · `POST /events/dead-letters/{id}/resolve` | `events.reprocess` | Operator actions |
| `POST /events/stream-ticket` · `GET /events/stream` | `events.read` | Live SSE updates |
| `GET /analytics/overview, events-by-type, events-over-time, failure-rates, processing-latency, top-sources, queue-status, dead-letters` | `analytics.read` | Analytics |
| `GET /admin/audit-logs` | `audit_logs.read` | Audit trail |

List endpoints take `limit` (1–200, default 50) and `offset`, and return `{items,total,limit,offset}`.
Time filters: `from` (inclusive) / `to` (exclusive), ISO-8601; analytics default to the last 24 hours.

---

## 7. Roles & permissions

Enforced **server-side on every endpoint** (FastAPI dependencies); permissions are re-read on every request, so
changes take effect immediately.

| Permission | ADMIN | OPERATOR | ANALYST | VIEWER |
|---|:-:|:-:|:-:|:-:|
| `events.read` | ✔ | ✔ | ✔ | ✔ |
| `events.read_payload` (see payload/metadata; otherwise redacted) | ✔ | ✔ | ✔ | ✘ |
| `events.reprocess` | ✔ | ✔ | ✘ | ✘ |
| `analytics.read` (also the live stream) | ✔ | ✔ | ✔ | ✔ |
| `users.read`, `users.manage`, `roles.manage`, `permissions.manage` | ✔ | ✘ | ✘ | ✘ |
| `api_keys.read`, `api_keys.manage`, `audit_logs.read` | ✔ | ✘ | ✘ | ✘ |
| `events.ingest` | ✔ (assignable; producers use API-key scopes) | | | |

Safety rails: system roles can't be deleted; the ADMIN role always holds every permission; you can't deactivate
yourself or remove the last active admin; deactivated users' tokens stop working immediately.

---

## 8. Event pipeline & delivery guarantees

**What the system guarantees (single instance):**
* An event answered with `202` is **already committed to PostgreSQL** (durable) before the response is sent.
* **Event-level de-duplication**: `event_id` is unique (DB constraint + atomic `INSERT … ON CONFLICT`). Concurrent
  duplicates cannot create two rows. Note: a duplicate is detected by `event_id` only — its payload is **not** compared.
* **At-least-once processing.** After a crash/shutdown, events that were `RECEIVED/QUEUED/RETRYING` are re-dispatched and
  events that were mid-`PROCESSING` are marked `INTERRUPTED` and retried. Therefore a handler can run more than once
  for one event → **handlers must be idempotent**.
* No two workers process the same event concurrently (atomic claim). Attempt history is kept per event.
* Memory is bounded: queue capacity is fixed; when full, ingestion returns `503 QUEUE_FULL` (+`Retry-After`) *before*
  persisting, so the producer retries and nothing is silently dropped. If the queue fills in the tiny window after
  persisting, the event stays `RECEIVED` in PostgreSQL and the sweeper dispatches it later.
* Graceful shutdown: workers stop taking work, in-flight events get `EVENT_SHUTDOWN_GRACE_SECONDS` to finish, stragglers are
  recorded as `INTERRUPTED` and resume on next start.
* Retries: `EVENT_MAX_RETRIES` retries after the first attempt (default 3 ⇒ up to 4 attempts), delay
  `base·2^(n-1)` capped. Handler timeouts count as retryable failures; `NonRetryableProcessingError` dead-letters immediately.

**What it does NOT guarantee:** exactly-once delivery, global ordering, distributed fault tolerance, or multi-instance
safety (the in-memory queue, SSE broker, rate limiter and stream tickets are per-process).

**Writing business logic:** register handlers per event type. The registry is created in the lifespan in `app/main.py`
(`app.state.handlers = HandlerRegistry()`); add your registrations right after that line, before the workers start:
```python
from app.services.processing_service import EventContext, NonRetryableProcessingError, ProcessingError

async def handle_order(ctx: EventContext) -> None:
    ...  # raise ProcessingError (retried) or NonRetryableProcessingError (straight to dead letter)

app.state.handlers.register("order.created", handle_order)
```
The default handler accepts the event unchanged — it is the extension point, not a placeholder claim.

**Event validation:** required fields, supported `schema_version` (`SUPPORTED_SCHEMA_VERSIONS`, default `1.0`), timezone-aware
timestamp (≤5 min in the future, ≤365 days old), payload/metadata ≤ `MAX_PAYLOAD_BYTES`, nesting ≤10, no NUL chars, and
type-specific payload rules for `order.created` (`order_id, amount≥0, currency`), `payment.succeeded|failed`
(`payment_id, amount, currency`), `user.activity` (`user_id, action`), `app.error` (`service, message`),
`service.health` (`service, status∈up|degraded|down`). Other event types accept any JSON object payload.

---

## 9. Analytics metric definitions
Window = `[from, to)` on `received_at` (default last 24 h). All numbers come from PostgreSQL aggregates.

| Metric | Definition |
|---|---|
| `total_received` | events received in the window |
| `processed` / `failed` / `pending` / `processing` | status = PROCESSED / (FAILED, DEAD_LETTER) / (RECEIVED, QUEUED, RETRYING) / PROCESSING |
| `success_rate`, `failure_rate` | `processed/(processed+failed)` and `failed/(processed+failed)`; **`null` when nothing has finished** (no divide-by-zero) |
| `events_per_minute` | `total_received ÷ window length (minutes)` |
| `duplicate_submissions` | sum of `duplicate_count` (re-submissions of an existing `event_id`) |
| `retries_total` | sum of `retry_count` |
| `avg_processing_latency_ms`; `p50/p95/p99` | over PROCESSED events (`percentile_cont`); `null` with no samples |
| `events-over-time` | `minute|hour|day` buckets, gap-filled with zeros (max 2000 buckets) |

---

## 10. Tests
Tests run against a **separate database** and refuse to run unless its name ends in `_test`. By default it is derived from
`DATABASE_URL` (`streampulse_db` → `streampulse_test`); or set `TEST_DATABASE_URL`. The schema is built with the real Alembic
migrations on every run.
```powershell
# one-time (already done by scripts/setup_database.sql): streampulse_test must exist
pytest                         # all tests (~2 min)
pytest tests/test_ingestion.py -q
pytest -k "concurrent or recovery" -v
```
Coverage: DB connectivity · migrations (sync/up/down) · login, JWT validation/expiry/revocation, lockout & throttling,
Argon2id · RBAC matrix, last-admin protection, payload redaction · API keys (create/once/revoke/expire/scope/rate/quota) ·
audit trail (no secrets) · ingestion validation, schema versions, batches, size limits, **concurrent duplicates**, tenant
isolation, request idempotency · processing, retries, dead letters, non-retryable errors, timeouts, manual reprocess &
authorization · **queue-full**, **restart recovery**, **graceful shutdown**, exactly-one-claim races · analytics math,
empty data, filters, pagination · SSE framing, bounded buffers, heartbeat, disconnect cleanup, ticket auth · CORS · health.

---

## 11. Load testing & measured results
```powershell
# 1) create a key with a high rate limit (default is 600 requests/min per key)
# 2) run:
python -m scripts.load_test --api-key sp_xxx --events 5000 --concurrency 20 --batch-size 50 `
   --duplicate-ratio 0.05 --seed 42 --username admin --password "YOUR_PASSWORD"
```
It is repeatable (`--seed`), reports request throughput, latency percentiles, accepted/duplicate/rejected counts,
429/503 backpressure, and — with admin credentials — queue utilisation and end-to-end processing throughput.

**What I actually measured** (Linux sandbox with **1 vCPU shared by uvicorn, PostgreSQL and the load generator**; INFO/WARNING
logging as noted; your Windows machine will differ — run it yourself and trust your numbers):

| Scenario | Result |
|---|---|
| Batch endpoint, 50 events/request, 10 clients, 2 workers (WARNING logs) | ingest **628–879 events/s**, request p50 48–94 ms, p95 169–412 ms; queue saturated → 20–37 requests got `503` + `Retry-After` and succeeded on retry; 0 failures |
| Same, then waiting for processing to drain | end-to-end **≈115 events/s** (2 workers) vs **≈122 events/s** (8 workers) |
| Single-event endpoint, 20 clients, 5% duplicates, INFO access logs | **≈64–80 req/s**, p50 ≈95–200 ms, p95 ≈285–295 ms; duplicates correctly returned as `200 duplicate` |
| Handler time (trivial default handler) | p50 ≈0.35 ms, p99 ≈6–7 ms (the cost is database round-trips, not the handler) |

Interpretation: with a trivial handler, throughput is bounded by **single-process Python + database round-trips on one core**
(adding workers from 2→8 did not help, and during the run `top` showed uvicorn as the busiest process on the single core — I did not profile further). The bounded queue and `503`
back-pressure behaved as designed under overload. On a multi-core machine expect more; the architecture note below
explains the real fix.

> **Scaling honestly:** PostgreSQL + one in-process queue is *not* a distributed pipeline. It will not match a message broker
> (Kafka/Redpanda) with multiple worker processes. That is the documented upgrade path (section 16).

---

## 12. Frontend integration notes
* **CORS:** put your frontend origin(s) in `CORS_ORIGINS` (e.g. `http://localhost:3000,http://localhost:5173`). No cookies are
  used, so `allow_credentials` is off; send the token in the `Authorization` header.
* **Auth flow:** `POST /auth/login` → keep `access_token` (memory or sessionStorage, not a long-lived cookie/localStorage if you can
  avoid it) → send `Authorization: Bearer …`. Tokens last `ACCESS_TOKEN_EXPIRE_MINUTES` (30). On `401` with code `TOKEN_EXPIRED`
  / `TOKEN_REVOKED` / `INVALID_TOKEN`, send the user back to login. There are no refresh tokens (documented limitation).
* **Role-aware UI:** call `GET /auth/me` → `permissions: ["events.read", …]` and hide what the user can't do. The server enforces
  everything regardless.
* **Live updates (SSE):** the browser `EventSource` can't set headers, so do
  1. `POST /events/stream-ticket` (Bearer auth) → `{ticket, expires_in_seconds}`
  2. `new EventSource(`${base}/api/v1/events/stream?ticket=${ticket}`)` (ticket is one-time, valid ~30 s).
  
  Event names: `connected`, `event.received`, `event.processing`, `event.processed`, `event.retrying`, `event.dead_lettered`,
  `event.reprocess_requested`, `overflow` (your buffer overflowed → refetch via REST). Heartbeat comments every 15 s. Messages carry
  ids/status only (no payloads). The stream is **not durable**; after reconnecting, reload data from `GET /events`/analytics.
  (`fetch()`-based SSE with a Bearer header also works.)
* **Charts:** `analytics/events-over-time` is already gap-filled; rates can be `null` (show "–").
* **Pagination:** `{items,total,limit,offset}`. **Errors:** always `{error:{code,message,request_id,details}}`; show `message`, log `request_id`.
* **Payload redaction:** for VIEWER users `payload`/`metadata` are `null` and `payload_redacted: true`.

---

## 13. Configuration reference
See `.env.example` (all keys documented there). Notable: `EVENT_WORKER_CONCURRENCY` (default 2), `EVENT_QUEUE_MAXSIZE` (1000),
`EVENT_MAX_RETRIES` (3), `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` (10/10 — keep `workers + expected concurrent requests` below the sum),
`LOG_JSON=false` for readable dev logs, `AUTO_SEED_RBAC` (default true: creates missing permissions/roles at startup, never overwrites
your customised non-ADMIN roles). Logs go to stdout and `logs/streampulse.log` (rotating).

---

## 14. Troubleshooting (Windows / PostgreSQL)

| Symptom | Likely cause / fix |
|---|---|
| `psql` is not recognized | Add `C:\Program Files\PostgreSQL\<ver>\bin` to PATH (see 3.1) |
| `password authentication failed for user "streampulse_app"` | Password in `.env` ≠ the one in `setup_database.sql`; URL-encode special characters. Reset: `psql -U postgres -c "ALTER ROLE streampulse_app PASSWORD 'new'"` |
| `ConnectionRefusedError … 5432` / app exits "PostgreSQL is unreachable" | PostgreSQL service not running: `services.msc` → *postgresql-x64-NN* → Start. Check port with `Get-NetTCPConnection -LocalPort 5432` |
| `database "streampulse_db" does not exist` | Run `scripts/setup_database.sql` (3.3) |
| `permission denied for schema public` | Re-run the `GRANT ALL ON SCHEMA public …` lines in the SQL file as `postgres` (PostgreSQL 15+ tightened `public`) |
| `alembic upgrade head` → "Target database is not up to date" / other | `alembic current`, then `alembic upgrade head`; never edit the DB by hand |
| `ValidationError … SECRET_KEY … at least 32 characters` | Run `python -m scripts.generate_secrets` and paste into `.env` |
| `.\.venv\Scripts\Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `pip install` fails building a package | Use Python 3.11/3.12 (64-bit) and `python -m pip install --upgrade pip` |
| Tests: "Refusing to run: the test database name must end with '_test'" | Create `streampulse_test` (SQL file) or set `TEST_DATABASE_URL` |
| `503 QUEUE_FULL` during load | Expected back-pressure: honour `Retry-After`, raise `EVENT_WORKER_CONCURRENCY`/`EVENT_QUEUE_MAXSIZE`, or slow producers |
| Port 8000 already in use | `uvicorn app.main:app --port 8001` |
| Behind a reverse proxy, all clients share one IP in logs/throttling | start uvicorn with `--proxy-headers --forwarded-allow-ips <proxy-ip>` |

---

## 15. Known limitations
* **Single instance only.** Queue, SSE broker, API-key/login rate limiter and stream tickets are in-process. Running several
  instances against one database would let one instance's startup recovery re-schedule another instance's in-flight events
  (still safe because of atomic claims, but duplicates of work). Don't use `uvicorn --workers N` yet.
* In-memory rate limiting resets on restart and is not shared across instances; the daily quota is counted from the database.
* No refresh tokens, MFA, email verification (`is_verified` is stored but not enforced) or password-reset emails (future work).
* Tenant scoping applies to **ingestion** (API-key ↔ `customer_id`). Dashboard users see events of all tenants according to their
  role; per-tenant dashboard isolation is future work.
* The default event handler is a no-op accept; real business logic is registered by you.
* Failed-login auditing records the account only when it exists; the account lock reveals existence of the account (`429 ACCOUNT_LOCKED`).

---

## 16. Future upgrade path (not implemented — nothing below is installed or required)
The seams are already modular: ingestion calls `EventWorkerManager.dispatch(ids)`; processing only touches
`processing_service`; analytics is pure SQL in `analytics_service`; the rate limiter and broker are small classes.

| Goal | How to evolve |
|---|---|
| Docker / Compose | Dockerfile for the app + `postgres` service; same `DATABASE_URL`; run `alembic upgrade head` as a release step |
| Kafka / Redpanda | Replace `dispatch()` with a producer and the worker loop with a consumer group; keep PostgreSQL state transitions (they are already idempotent) |
| Redis | Swap `SlidingWindowRateLimiter`, stream tickets and the SSE broker for Redis-backed versions (pub/sub for fan-out) |
| Dedicated worker processes | Run the worker loop as its own entrypoint (`python -m worker`), keep the atomic `claim_event`; move startup recovery to a lease/heartbeat model first |
| PostgreSQL tuning | Partition `events` by `received_at`, retention jobs, pre-aggregated rollups, `pg_stat_statements`, PgBouncer |
| Prometheus / Grafana / OpenTelemetry | Add `/metrics` and tracing around `processing_service` and the middleware |
| CI/CD | Run `pytest` + `alembic check` against a service container |
| Advanced tenant isolation | Tenant claim on dashboard users, row-level security policies |
