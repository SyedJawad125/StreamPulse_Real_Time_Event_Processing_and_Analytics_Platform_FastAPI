<div align="center">

# ⚙️ Enterprise AI Workflow & Automation Platform

### FastAPI Microservices · Event-Driven Architecture · Human-in-the-Loop AI

<em>Create Workflow → AI Analysis (LangGraph) → Risk Gate → Human Approval → Integration Action → Notify → Audit</em>

<br/>

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL_16-Schema--per--Service-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.13-FF6600?style=for-the-badge&logo=rabbitmq&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.4-37814A?style=for-the-badge&logo=celery&logoColor=white)

![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2-FF6B35?style=for-the-badge)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-46%20passing-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)
![Status](https://img.shields.io/badge/Status-Portfolio%20Project-orange?style=for-the-badge)

<br/>

**A distributed backend where AI is one component of a larger system — not the whole app.**
7 independently deployable services. Real event-driven retries and dead-letter queues. A human always approves the risky action.

<br/>

[✨ Features](#-features) • [🏗️ Architecture](#️-architecture) • [🚀 Quick Start](#-quick-start) • [🌐 API Reference](#-api-reference) • [🧠 Design Notes](#-design-decisions-worth-knowing-for-an-interview)

</div>

<br/>

---

## 📖 Table of Contents

- [About](#-about)
- [Features](#-features)
- [Architecture](#️-architecture)
- [Workflow Execution State Machine](#-workflow-execution-state-machine)
- [AI Reasoning Flow (LangGraph)](#-ai-reasoning-flow-langgraph)
- [RabbitMQ Retry & Dead-Letter Design](#-rabbitmq-retry--dead-letter-design)
- [Tech Stack](#️-tech-stack)
- [Project Structure](#-project-structure)
- [Quick Start](#-quick-start)
- [Environment Variables](#️-environment-variables)
- [API Reference](#-api-reference)
- [API Examples](#-api-examples)
- [Database Schema](#️-database-schema)
- [Security](#-security-features)
- [Testing](#-testing)
- [Design Decisions](#-design-decisions-worth-knowing-for-an-interview)
- [Roadmap](#️-roadmap)

---

## 📌 About

Real enterprise workflows aren't "call an LLM, return the answer." They're multi-step, they touch external systems, they sometimes fail halfway through, and some decisions are too risky to let an AI make alone.

**This platform demonstrates that distributed-systems reality**, using a customer-refund workflow as the running example:

> A customer request comes in → **AI Service** runs a LangGraph reasoning flow (intent → plan → tool lookups → decision) → if the refund is high-risk, the workflow pauses for **human approval** → once approved, **Integration Service** executes the refund idempotently → **Notification Service** tells the customer → every step along the way is published to **Audit Service** for a full, correlation-ID-traceable record.

Built to demonstrate real distributed-systems and AI-safety architecture, not just an LLM call wrapped in a route:

<table>
<tr>
<td width="50%">

**🧍 Human-in-the-loop by construction**
The AI recommends; it never executes a side effect. Integration Service's refund endpoint is only ever called by a worker acting on an explicit approval — structurally, not by convention.

</td>
<td width="50%">

**♻️ Real retries, real dead-letter queues**
A fixed 5s/15s/30s retry schedule, but only for errors that could plausibly succeed on retry. A 4xx fails once, immediately. Exhausted retries land in an inspectable RabbitMQ DLQ, not a swallowed log line.

</td>
</tr>
<tr>
<td width="50%">

**🔁 Idempotent by design**
Both workflow execution and the refund call accept an `Idempotency-Key`. A retried request — or a Celery redelivery after a crash — returns the original result instead of doing the work twice.

</td>
<td width="50%">

**🧵 Traceable end to end**
One `correlation_id` is generated at the Gateway and threaded through every HTTP call, every Celery task, and every audit event — across all 7 services — so one failed execution can be reconstructed from logs alone.

</td>
</tr>
</table>

---

## ✨ Features

| Feature | Description | Status |
|---|---|:---:|
| 🚪 API Gateway | Single public entry point — JWT verification, RBAC, rate limiting, CORS, correlation IDs | ✅ |
| 🔐 Auth Service | JWT access + refresh tokens, rotation-on-use, 4 roles × 7 permissions | ✅ |
| 🧠 Workflow Service | The state machine — executions, step tracking, approvals, idempotent execute | ✅ |
| 🤖 AI Service | LangGraph reasoning flow, pluggable `LLMProvider`, Pydantic-validated structured output | ✅ |
| 🔌 Integration Service | Mocked Customer/Order/Ticket/Payment APIs, idempotent refund endpoint | ✅ |
| 📣 Notification Service | Mock email/in-app/webhook delivery abstraction | ✅ |
| 📜 Audit Service | Immutable event log, raw-AMQP consumer with retry cascade + DLQ | ✅ |
| ⚙️ 3 Celery Workers | ai-worker, integration-worker, notification-worker — async, retried, dead-letterable | ✅ |
| 🧍 Human-in-the-Loop Gate | `WAITING_FOR_APPROVAL` state; AI can never bypass it | ✅ |
| 🔁 Idempotency | On workflow execution *and* the refund call, not just one of them | ✅ |
| 🪪 Correlation IDs | Propagated both directions — including worker-to-service callbacks | ✅ |
| ♻️ Retry / DLQ | Fixed 5s/15s/30s schedule, retryable-error classification, real RabbitMQ dead-lettering | ✅ |
| 🏥 Health & Readiness | `/health` (liveness) + `/ready` (timeout-bounded dependency checks) | ✅ |
| 🗄️ Schema-per-Service | 5 Postgres schemas, zero cross-schema access | ✅ |
| 🧮 Alembic Migrations | Real, async-aware migration on workflow-service (reference pattern) | ✅ |
| 📊 AI Evaluation Harness | 100 synthetic requests → intent/structured-output/approval-gate accuracy | ✅ |
| 🧪 46 Automated Tests | Per-service suites, isolated by `PYTHONPATH`, zero shared-package collisions | ✅ |
| 🌐 E2E Test Suite | Hits the real running stack over HTTP, self-skips if the stack isn't up | ✅ |
| 🐳 No-Docker Mode | `python start.py` — SQLite + single venv, real RabbitMQ/Redis still required | ✅ |
| 📬 Postman Collection | Full endpoint list with auto-token-capture scripts | ✅ |

---

## 🏗️ Architecture

```
                              ┌────────────────────┐
                              │  Frontend (static)  │
                              └──────────┬───────────┘
                                         │ HTTPS
                                         ▼
                              ┌────────────────────┐
                              │    API Gateway      │   JWT · RBAC · Rate Limit · CORS
                              │      :8000          │   Correlation-ID origin
                              └──────────┬───────────┘
                     ┌────────────────────┼────────────────────┐
                     ▼                    ▼                    ▼
            ┌────────────────┐  ┌──────────────────┐  ┌────────────────┐
            │  Auth Service   │  │ Workflow Service  │  │ Audit Service  │
            │     :8001       │  │      :8002        │  │     :8006      │
            │  JWT · RBAC     │  │  State Machine     │  │  Event Log     │
            └─────────────────┘  │  Approvals         │  │  Retry+DLQ     │
                                  └─────────┬──────────┘  └────────▲───────┘
                                            │ dispatch              │ events
                                            ▼ (Celery / RabbitMQ)    │
                        ┌──────────────────┼───────────────────┐    │
                        ▼                  ▼                   ▼    │
                ┌───────────────┐ ┌───────────────────┐ ┌─────────────────┐
                │   ai-worker    │ │ integration-worker │ │ notification-   │
                │                │ │                     │ │    worker       │
                └───────┬────────┘ └──────────┬──────────┘ └────────┬────────┘
                        │ HTTP                 │ HTTP                │ HTTP
                        ▼                      ▼                     ▼
                ┌───────────────┐ ┌───────────────────┐ ┌─────────────────┐
                │  AI Service    │ │ Integration Service │ │ Notification    │
                │    :8003       │ │       :8004          │ │ Service :8005   │
                │  LangGraph     │ │  Mock Customer/Order/ │ │  Mock email/    │
                │  LLMProvider   │ │  Ticket/Payment APIs  │ │  in-app/webhook │
                └───────┬────────┘ └───────────────────────┘ └─────────────────┘
                        │ controlled tool calls
                        ▼
                (back into Integration Service — read-only lookups only)

              ────────────────────────  Infrastructure  ────────────────────────
              PostgreSQL 16 (schema-per-service)  ·  Redis (rate limit + Celery backend)
              RabbitMQ (Celery broker + audit topic exchange, retry cascade, DLQs)
```

Every worker reports back to Workflow Service over HTTP after it finishes — that callback is what advances the state machine. Nothing polls; everything is event-driven or explicitly dispatched.

---

## 🔄 Workflow Execution State Machine

```
   CREATE WORKFLOW
         │
         ▼
   POST .../execute  (Idempotency-Key honored)
         │
         ▼
      QUEUED → RUNNING  ──────► dispatch: ai_analysis step
                                        │
                                        ▼
                              AI Service runs LangGraph
                                        │
                     ┌──────────────────┼───────────────────┐
                     ▼                  ▼                    ▼
              requires_approval   low-risk, auto-proceed   lookup failed
                     │                  │                    │
                     ▼                  ▼                    ▼
          WAITING_FOR_APPROVAL   dispatch: execute_action   FAILED
                     │                  │               (fail-safe — never
           ┌─────────┴─────────┐        │                silently approved)
           ▼                   ▼        │
       approve              reject       │
           │                   │         │
           ▼                   ▼         │
  dispatch: execute_action  CANCELLED     │
           │                   │         │
           └─────────┬─────────┘         │
                      ▼                  ▼
              dispatch: notify  ◄─────────┘
                      │
                      ▼
            COMPLETED / FAILED
                      │
                      ▼
              (audit trail complete,
               queryable by correlation_id)
```

> A failed customer/order lookup during AI analysis routes straight to `FAILED` — not to human approval. Asking a human to approve a decision built on missing data would be the wrong default, so the system doesn't do that.

---

## 🧠 AI Reasoning Flow (LangGraph)

```
            INPUT (input_text, customer_id, order_id)
                           │
                           ▼
                   intent_analysis
              (classify: refund / support / general)
                           │
                           ▼
                       planning
             (which lookups does this intent need?)
                           │
                           ▼
                   tool_execution
        (controlled, Pydantic-validated tool calls only —
         customer_lookup / order_lookup / ticket_lookup)
                           │
                           ▼
                      validation
              (did every tool call succeed?)
                 ┌─────────┴─────────┐
                 ▼                   ▼
            all succeeded        any failed
                 │                   │
                 ▼                   ▼
               decide          decision = "fail"
       (LLM recommends;              │
        Pydantic-validated;          │
        repair-retry once if         │
        invalid; fail-safe if        │
        still invalid)               │
                 └─────────┬─────────┘
                           ▼
                          END
            (decision handed back to Workflow
             Service — AI never executes anything)
```

> `LangGraph` is scoped to *only* this reasoning sub-flow. The deterministic workflow state machine above is plain Python/SQLAlchemy on purpose — see [Design Decisions](#-design-decisions-worth-knowing-for-an-interview).

---

## ♻️ RabbitMQ Retry & Dead-Letter Design

Two different retry mechanisms, used deliberately in different places:

```
Celery-backed queues (ai / integration / notification processing)
──────────────────────────────────────────────────────────────────
  task fails → retryable? ──NO──► report failure, fail immediately
       │ YES
       ▼
  self.retry(countdown = 5s → 15s → 30s)
       │
       ▼ (retries exhausted)
  report failure to Workflow Service
       +
  re-raise  ──►  task_acks_on_failure_or_timeout=False
                          │
                          ▼
              RabbitMQ dead-letters the message
                          │
                          ▼
                   <queue>.dlq  (inspectable in
                   the RabbitMQ management UI)


Audit Service's raw-AMQP consumer (no task framework underneath it)
──────────────────────────────────────────────────────────────────
  audit.queue → processing fails
       │
       ▼
  audit.retry.queue  (per-message TTL: 5s / 15s / 30s,
                       chosen from a retry-count header)
       │  TTL expires
       ▼
  dead-lettered back into events.exchange
       │
       ▼
  re-delivered to audit.queue  (retry again, up to 3 attempts)
       │  attempts exhausted
       ▼
  audit.queue.dlq  (terminal)
```

A 4xx response (e.g. an order that doesn't exist) is **never retried** — only network failures and 5xx responses are, since retrying a request that was rejected outright burns time for zero chance of success and, for a side-effecting call like a refund, adds pure risk.

---

## 🛠️ Tech Stack

<table>
<tr><td><b>Framework</b></td><td>FastAPI 0.115 · Uvicorn · Pydantic v2</td></tr>
<tr><td><b>Database</b></td><td>PostgreSQL 16, schema-per-service · SQLAlchemy 2.0 async · SQLite for no-Docker local dev</td></tr>
<tr><td><b>Migrations</b></td><td>Alembic — async-aware, implemented on workflow-service as the reference pattern</td></tr>
<tr><td><b>Message Broker</b></td><td>RabbitMQ 3.13 — topic exchange, routing keys, DLX/DLQ, management UI</td></tr>
<tr><td><b>Background Jobs</b></td><td>Celery 5.4 — broker=RabbitMQ, backend=Redis, fixed retry schedule</td></tr>
<tr><td><b>Caching / Rate Limiting</b></td><td>Redis 7 — fixed-window counters at the Gateway</td></tr>
<tr><td><b>AI Orchestration</b></td><td>LangGraph 0.2 — scoped to the AI reasoning sub-flow only</td></tr>
<tr><td><b>LLM Provider</b></td><td>Pluggable <code>LLMProvider</code> interface — Mock (default, zero-cost) / OpenAI / Groq / Gemini</td></tr>
<tr><td><b>Auth</b></td><td>JWT (PyJWT) + bcrypt (passlib), refresh-token rotation</td></tr>
<tr><td><b>Testing</b></td><td>pytest + pytest-asyncio, SQLite-backed per-service suites + a real HTTP E2E suite</td></tr>
<tr><td><b>Containerization</b></td><td>Docker + Docker Compose (14 services, healthchecks, restart policies)</td></tr>
</table>

---

## 📂 Project Structure

<details>
<summary><b>Click to expand full directory tree</b></summary>

```
enterprise-ai-platform/
├── services/
│   ├── api-gateway/            app/{main,auth,rate_limit,core/config}.py
│   ├── auth-service/           app/{main,models,schemas,security,db,core/config}.py
│   ├── workflow-service/       app/{main,models,schemas,orchestrator,events,tasks_client,db}.py
│   │                           alembic/ (real migrations — reference pattern)
│   ├── ai-service/             app/{main,models,schemas,langgraph_flow,tools,db}.py
│   │                           app/providers/{base,factory,mock,openai,groq,gemini}_provider.py
│   ├── integration-service/    app/{main,mock_data,schemas}.py
│   ├── notification-service/   app/main.py
│   └── audit-service/          app/{main,consumer,models,db}.py
├── workers/
│   ├── ai-worker/tasks.py
│   ├── integration-worker/tasks.py
│   └── notification-worker/tasks.py
├── shared/                     # imported by every service — kept deliberately thin
│   ├── event_contracts/        EventEnvelope + per-event Pydantic payloads
│   ├── exceptions/             one error envelope every service returns
│   ├── logging/                structured JSON logger + correlation-ID middleware
│   ├── messaging/               celery_app factory, retry_policy, audit publisher
│   ├── health/                 /ready dependency-check helpers
│   ├── security/                JWT encode/decode, role → permission map
│   └── db_utils/                Postgres/SQLite compatibility layer
├── frontend/                    static dashboard (full Next.js app is on the roadmap)
├── infrastructure/postgres/     schema init SQL
├── docs/
│   ├── architecture/            design docs + the full audit-findings report
│   └── decisions/                ADR-001 .. ADR-012
├── eval/                         synthetic dataset + AI evaluation harness
├── tests/e2e/                   real-stack, self-skipping end-to-end tests
├── postman/                     importable collection + environment
├── docker-compose.yml
├── start.py                     run everything with no Docker (SQLite + venv)
├── requirements-local.txt
└── README.md
```

</details>

---

## 🚀 Quick Start

### Prerequisites
- Docker + Docker Compose **or** Python 3.12+ with RabbitMQ and Redis installed locally
- No LLM API key required — `LLM_PROVIDER=mock` is the default and runs the full reasoning flow deterministically

### 🐳 With Docker (recommended — matches the real architecture exactly)

```bash
cp .env.example .env
make up                       # docker compose up --build -d
make logs                     # tail every service's logs
```

Migrations for workflow-service run automatically as part of its container startup. Open `http://localhost:3000` for the dashboard, or `http://localhost:15672` for the RabbitMQ management UI (guest/guest).

### 💻 Without Docker

```bash
python start.py               # installs a single local venv, launches all 10 processes
```

Requires RabbitMQ and Redis running locally (the script checks and prints install instructions if they're not reachable). Uses SQLite instead of Postgres — see [Design Decisions](#-design-decisions-worth-knowing-for-an-interview) for how the same application code supports both without an if/else per service.

📍 Gateway at `http://localhost:8000` · Per-service interactive docs at `http://localhost:800{1-6}/docs`

---

## ⚙️ Environment Variables

<details>
<summary><b>Click to expand full <code>.env</code> reference</b></summary>

```env
# Database (Docker/Postgres mode)
POSTGRES_USER=platform
POSTGRES_PASSWORD=platform
POSTGRES_DB=platform
AUTH_DATABASE_URL=postgresql+asyncpg://platform:platform@postgres:5432/platform?options=-csearch_path%3Dauth
WORKFLOW_DATABASE_URL=postgresql+asyncpg://platform:platform@postgres:5432/platform?options=-csearch_path%3Dworkflow
AI_DATABASE_URL=postgresql+asyncpg://platform:platform@postgres:5432/platform?options=-csearch_path%3Dai
AUDIT_DATABASE_URL=postgresql+asyncpg://platform:platform@postgres:5432/platform?options=-csearch_path%3Daudit

# Redis / RabbitMQ
REDIS_URL=redis://redis:6379/0
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672//

# Auth
JWT_SECRET=change-me-to-a-long-random-string
ACCESS_TOKEN_TTL_SECONDS=900
REFRESH_TOKEN_TTL_SECONDS=1209600

# LLM provider abstraction — mock needs no key, whole platform runs end to end
LLM_PROVIDER=mock
LLM_MODEL=mock-decision-v1
OPENAI_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=

# Retry schedule (seconds), used by every Celery worker + the audit consumer
RETRY_DELAYS_SECONDS=5,15,30

# Gateway
GATEWAY_CORS_ORIGINS=*

# Service discovery (docker-compose network)
AUTH_SERVICE_URL=http://auth-service:8001
WORKFLOW_SERVICE_URL=http://workflow-service:8002
AI_SERVICE_URL=http://ai-service:8003
INTEGRATION_SERVICE_URL=http://integration-service:8004
NOTIFICATION_SERVICE_URL=http://notification-service:8005
AUDIT_SERVICE_URL=http://audit-service:8006

ENVIRONMENT=development
LOG_LEVEL=INFO
```

</details>

---

## 🌐 API Reference

<details open>
<summary><b>🔑 Authentication</b></summary>
<br/>

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | none | body: `email`, `password`, `role` |
| `POST` | `/api/v1/auth/login` | none | returns `access_token`, `refresh_token` |
| `POST` | `/api/v1/auth/refresh` | none | rotates + revokes the old refresh token |
| `POST` | `/api/v1/auth/logout` | none | revokes the refresh token |

</details>

<details open>
<summary><b>🧠 Workflows</b></summary>
<br/>

| Method | Endpoint | Permission | Description |
|---|---|---|---|
| `POST` | `/api/v1/workflows` | `workflow:create` | body: `name`, `description` |
| `GET` | `/api/v1/workflows/{workflow_id}` | `workflow:read` | |
| `POST` | `/api/v1/workflows/{workflow_id}/execute` | `workflow:execute` | body: `input_text`, `customer_id`, `order_id`; optional header `Idempotency-Key` |
| `GET` | `/api/v1/workflows/executions/{execution_id}/status` | `workflow:read` | full step-by-step timeline |

</details>

<details open>
<summary><b>🧍 Approvals</b></summary>
<br/>

| Method | Endpoint | Permission | Description |
|---|---|---|---|
| `GET` | `/api/v1/approvals` | `workflow:approve` | lists PENDING approvals |
| `POST` | `/api/v1/approvals/{approval_id}/approve` | `workflow:approve` | body: `decided_by` |
| `POST` | `/api/v1/approvals/{approval_id}/reject` | `workflow:approve` | |

</details>

<details open>
<summary><b>📜 Audit</b></summary>
<br/>

| Method | Endpoint | Permission | Description |
|---|---|---|---|
| `GET` | `/api/v1/audit/events` | `audit:read` | query: `workflow_id`, `execution_id`, `event_type`, `page`, `page_size` |

</details>

<details>
<summary><b>🏥 Health (click to expand — all 7 services)</b></summary>
<br/>

| Service | Health | Ready |
|---|---|---|
| api-gateway | `GET :8000/health` | — |
| auth-service | `GET :8001/health` | `GET :8001/ready` |
| workflow-service | `GET :8002/health` | `GET :8002/ready` |
| ai-service | `GET :8003/health` | `GET :8003/ready` |
| integration-service | `GET :8004/health` | — (no external dependencies to check) |
| notification-service | `GET :8005/health` | — (no external dependencies to check) |
| audit-service | `GET :8006/health` | `GET :8006/ready` |

</details>

<div align="center">

**13 public Gateway endpoints** · a **Postman collection** with auto-token-capture is included in `postman/`

</div>

---

## 💡 API Examples

<details>
<summary><b>Login</b></summary>

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "password123"}'
```
</details>

<details>
<summary><b>Execute a high-value refund (triggers the approval gate)</b></summary>

```bash
curl -X POST http://localhost:8000/api/v1/workflows/{workflow_id}/execute \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: unique-key-123" \
  -d '{
        "input_text": "I received the wrong product and want a refund of $250.",
        "customer_id": "cust_1001",
        "order_id": "ord_5001"
      }'
```

Response:
```json
{
  "execution_id": "a1b2c3d4-...",
  "correlation_id": "e5f6g7h8-...",
  "status": "QUEUED",
  "idempotent_replay": false
}
```
</details>

<details>
<summary><b>Trace one execution across every service</b></summary>

```bash
curl "http://localhost:8000/api/v1/audit/events?execution_id={execution_id}" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Returns every event — `workflow.started`, `ai.completed`, `approval.requested`, `approval.completed`, `integration.completed`, `workflow.completed` — all stamped with the same `correlation_id`.
</details>

---

## 🗄️ Database Schema

<details>
<summary><b>Click to expand schema diagram (5 Postgres schemas, zero cross-schema access)</b></summary>

```
auth                          workflow
──────────                    ──────────────────────
users                         workflows
refresh_tokens                workflow_executions  (idempotency_key, unique per workflow)
                               step_executions
                               approvals
                               execution_events

ai                             audit
──────────                     ──────────────────
ai_requests                    audit_events  (event_id unique — idempotent on redelivery)
ai_responses
model_configurations
token_usage

integration
──────────────────
idempotency_keys   (payment idempotency store)
mock_customers / mock_orders / mock_tickets / mock_payments
```

</details>

---

## 🔐 Security Features

- 🔑 JWT access (15min) + refresh (14 days) tokens, refresh tokens rotated and revoked-on-reuse
- 🔒 bcrypt password hashing (passlib)
- 🛡️ RBAC — 4 roles (`ADMIN`, `OPERATOR`, `APPROVER`, `USER`) × 7 explicit permissions, enforced at the Gateway *and* re-checked per service
- 🌐 CORS configured at the Gateway, origin allowlist via `GATEWAY_CORS_ORIGINS`
- 🚦 Redis-backed rate limiting on auth, workflow-create, and workflow-execute endpoints
- 🔁 Idempotency on every side-effecting operation — workflow execution and the refund call
- 🧍 Human approval required before any high-risk side-effecting action; enforced structurally, not by convention
- 🚫 The LLM never gets direct database or arbitrary HTTP access — only explicitly registered, Pydantic-validated tools
- 📝 Structured logs never contain passwords, JWTs, or API keys — by discipline in every log call site

---

## 🧪 Testing

```bash
# Per-service suites (isolated PYTHONPATH — avoids same-named `app` package collisions)
cd services/auth-service && PYTHONPATH=.:../.. pytest tests/ -v
cd services/api-gateway && PYTHONPATH=.:../.. pytest tests/ -v
cd services/ai-service && PYTHONPATH=.:../.. pytest tests/ -v
cd services/integration-service && PYTHONPATH=.:../.. pytest tests/ -v
cd services/notification-service && PYTHONPATH=.:../.. pytest tests/ -v
cd services/workflow-service && PYTHONPATH=.:../.. pytest tests/ -v
cd services/audit-service && PYTHONPATH=.:../.. pytest tests/ -v
PYTHONPATH=. pytest shared/tests/ -v

# End-to-end, against the real running stack (self-skips if it isn't up)
docker compose up -d
pytest tests/e2e -v -m e2e

# AI evaluation harness
cd eval && python generate_dataset.py
cd ../services/ai-service && PYTHONPATH=.:../.. python ../../eval/run_eval.py
```

**46 passing automated tests** across 7 services + shared logic, plus 2 end-to-end tests that exercise the real stack over HTTP with nothing mocked.

---

## 🧠 Design Decisions Worth Knowing for an Interview

> 💡 **LangGraph is scoped to the AI reasoning sub-flow only.** The workflow state machine (`CREATED → RUNNING → WAITING_FOR_APPROVAL → COMPLETED/FAILED`) is plain Python/SQLAlchemy on purpose — it's deterministic orchestration, not AI reasoning, and doesn't need an AI framework underneath it.

> 💡 **Two retry mechanisms exist, deliberately, not by accident.** Celery already *is* a retry mechanism, so the three worker queues use its native `self.retry()`. Audit Service's consumer has no task framework underneath it, so it implements the classic RabbitMQ TTL-cascade pattern by hand. Using the same mechanism everywhere "for consistency" would mean picking the worse-fitting tool in one of the two places.

> 💡 **A 4xx is never retried.** Only network failures and 5xx responses are — retrying a request that was rejected outright wastes the full backoff schedule for zero chance of success, and for a side-effecting call like a refund, unnecessary retries are pure added risk.

> 💡 **The LLM never executes a side effect — structurally, not by convention.** Integration Service's refund endpoint is only ever called by a worker acting on Workflow Service's explicit dispatch after approval. There is no code path from AI Service to a side-effecting action, so a prompt-injected or hallucinating model has nothing to exploit.

> 💡 **A failed data lookup fails the step — it does not ask a human to approve a guess.** Early versions of this project routed tool-lookup failures to the human-approval queue; that's the wrong default; it now fails the workflow cleanly instead, caught and fixed during an explicit audit pass (see `docs/architecture/audit-findings.md`).

> 💡 **The same application code runs against Postgres or SQLite, with zero per-service if/else.** A shared `shared/db_utils` helper strips schema qualifiers only when the dialect is SQLite, which is what lets `python start.py` skip Postgres entirely for local dev while Docker/production mode stays byte-for-byte unchanged.

> 💡 **`shared/` holds infrastructure plumbing only, never business logic.** If workflow decisions lived there, every service would be silently coupled to them — the one rule that keeps 7 services from quietly becoming a distributed monolith.

---

## 🗺️ Roadmap

- [x] 7 FastAPI microservices, schema-per-service PostgreSQL
- [x] RabbitMQ event-driven architecture with real retry/DLQ cascades
- [x] Celery background workers with a fixed, retryable-error-aware retry schedule
- [x] LangGraph AI reasoning flow + pluggable LLM provider abstraction
- [x] Human-in-the-loop approval gate, enforced structurally
- [x] Idempotency on every side-effecting operation
- [x] Correlation-ID tracing across all 7 services, both directions
- [x] JWT auth + granular RBAC
- [x] Alembic migrations (workflow-service, reference pattern)
- [x] 46 automated tests + a self-skipping E2E suite
- [x] AI evaluation harness
- [x] No-Docker local run (`start.py`, SQLite + single venv)
- [x] Postman collection with auto-token-capture
- [ ] Alembic for auth/ai/audit services (workflow-service is the reference to extend)
- [ ] OpenTelemetry distributed tracing
- [ ] True database-per-service (separate Postgres instances)
- [ ] Full Next.js dashboard

---

<div align="center">

### 📄 License

No formal license file is included yet — treat this as a portfolio/educational project unless a `LICENSE` is added.

<br/>

**Built with FastAPI · RabbitMQ · Celery · Redis · PostgreSQL · LangGraph · Docker**

⭐ *If this project helped you understand distributed AI-system design, consider giving it a star.*

</div>