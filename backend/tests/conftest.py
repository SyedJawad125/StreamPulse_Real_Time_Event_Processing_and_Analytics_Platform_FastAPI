"""Test harness.

Safety: tests ONLY run against a database whose name ends in `_test`. Set TEST_DATABASE_URL, or let it be derived
from DATABASE_URL (`streampulse_db` -> `streampulse_test`). The dev database is never touched.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def _derive_test_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    if not base:
        pytest.exit("Set TEST_DATABASE_URL (e.g. postgresql+psycopg2://streampulse_app:PASSWORD@localhost:5432/streampulse_test)", 2)
    head, _, name = base.rpartition("/")
    name = name.split("?")[0]
    if name.endswith("_test"):
        return base
    stem = name[:-3] if name.endswith("_db") else name  # streampulse_db -> streampulse_test
    return f"{head}/{stem}_test"


TEST_DATABASE_URL = _derive_test_url()
if not TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0].endswith("_test"):
    pytest.exit("Refusing to run: the test database name must end with '_test'", 2)

os.environ.update({
    "DATABASE_URL": TEST_DATABASE_URL,
    "APP_ENV": "testing",
    "SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    "API_KEY_PEPPER": "test-pepper-test-pepper-test-pepper-0123456789",
    "LOG_JSON": "false", "LOG_LEVEL": "ERROR", "CORS_ORIGINS": "",
    # fast retry/sweep timings so pipeline tests finish quickly
    "EVENT_QUEUE_MAXSIZE": "100", "EVENT_WORKER_CONCURRENCY": "2", "EVENT_MAX_RETRIES": "2",
    "EVENT_RETRY_BASE_DELAY_SECONDS": "0.05", "EVENT_RETRY_MAX_DELAY_SECONDS": "0.2",
    "EVENT_SWEEP_INTERVAL_SECONDS": "0.1", "EVENT_SHUTDOWN_GRACE_SECONDS": "1.0",
    "LOGIN_IP_LIMIT_PER_MINUTE": "10000", "SSE_HEARTBEAT_SECONDS": "0.2",
})

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.main import app  # noqa: E402
from tests.helpers import login_headers, make_user  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Build the schema with the real Alembic migrations (this exercises them on every run)."""
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=os.environ.copy(),
                            capture_output=True, text=True)
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"


@pytest.fixture(autouse=True)
def clean_database(migrated_database):
    engine = create_engine(TEST_DATABASE_URL, poolclass=NullPool)
    with engine.begin() as conn:
        names = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                                  "AND tablename <> 'alembic_version'")).scalars().all()
        if names:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{n}"' for n in names) + " RESTART IDENTITY CASCADE"))
    engine.dispose()
    yield


@pytest.fixture
def client():
    """App with its lifespan running: RBAC seeded, event workers started."""
    from app.rate_limit import SlidingWindowRateLimiter
    app.state.rate_limiter = SlidingWindowRateLimiter(60.0)  # DB ids restart each test; don't leak limiter state
    with TestClient(app) as c:
        yield c


@pytest.fixture
def manager(client):
    return client.app.state.worker_manager


@pytest.fixture
def admin_headers(client):
    make_user("admin@example.com", "su", superuser=True)
    return login_headers(client, "admin@example.com")


@pytest.fixture
def operator_headers(client):
    make_user("operator@example.com", "operator")
    return login_headers(client, "operator@example.com")


@pytest.fixture
def analyst_headers(client):
    make_user("analyst@example.com", "analyst")
    return login_headers(client, "analyst@example.com")


@pytest.fixture
def viewer_headers(client):
    make_user("viewer@example.com", "viewer")
    return login_headers(client, "viewer@example.com")


@pytest.fixture
def api_key(client, admin_headers):
    r = client.post("/api/api-keys/v1/api-key/", json={"name": "test-key"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()["key"]


@pytest.fixture
def key_headers(api_key):
    return {"X-API-Key": api_key}
