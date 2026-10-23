"""Test harness.

Safety: tests ONLY run against a database whose name ends in `_test`. Set TEST_DATABASE_URL, or let it be
derived from DATABASE_URL by appending `_test` to the database name. The dev database is never touched.
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
        pytest.exit("Set TEST_DATABASE_URL (e.g. postgresql+asyncpg://streampulse_app:PASSWORD@localhost:5432/streampulse_test)", 2)
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
    "LOG_JSON": "false",
    "LOG_LEVEL": "ERROR",
    "CORS_ORIGINS": "",
})

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from tests.helpers import Harness, auth_headers, make_user, running_app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Build the schema with the real Alembic migrations (this exercises them on every run)."""
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
                            env=os.environ.copy(), capture_output=True, text=True)
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr}"


@pytest.fixture(autouse=True)
async def clean_database(migrated_database):
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        names = (await conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"))).scalars().all()
        if names:
            await conn.execute(text("TRUNCATE " + ", ".join(f'"{n}"' for n in names) + " RESTART IDENTITY CASCADE"))
    await engine.dispose()
    yield


@pytest.fixture
async def h():
    async with running_app() as harness:
        yield harness


@pytest.fixture
async def admin_headers(h: Harness):
    await make_user(h, "admin", ["ADMIN"])
    return await auth_headers(h, "admin")


@pytest.fixture
async def operator_headers(h: Harness):
    await make_user(h, "operator1", ["OPERATOR"])
    return await auth_headers(h, "operator1")


@pytest.fixture
async def analyst_headers(h: Harness):
    await make_user(h, "analyst1", ["ANALYST"])
    return await auth_headers(h, "analyst1")


@pytest.fixture
async def viewer_headers(h: Harness):
    await make_user(h, "viewer1", ["VIEWER"])
    return await auth_headers(h, "viewer1")


@pytest.fixture
async def api_key(h: Harness, admin_headers):
    r = await h.client.post("/api/v1/api-keys", json={"name": "test-key"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()["key"]


@pytest.fixture
def key_headers(api_key):
    return {"X-API-Key": api_key}
