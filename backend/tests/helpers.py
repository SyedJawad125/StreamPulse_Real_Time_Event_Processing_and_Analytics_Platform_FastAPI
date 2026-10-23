from __future__ import annotations

import asyncio
import itertools
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app
from app.schemas.user import UserCreate
from app.services import user_service

PASSWORD = "Str0ng-Passw0rd!"

BASE_OVERRIDES: dict[str, Any] = dict(
    app_env="testing", event_queue_maxsize=100, event_worker_concurrency=2, event_max_retries=2,
    event_retry_base_delay_seconds=0.05, event_retry_max_delay_seconds=0.2, event_sweep_interval_seconds=0.1,
    event_shutdown_grace_seconds=1.0, db_pool_size=8, db_max_overflow=8, login_ip_limit_per_minute=10_000,
    log_level="ERROR", sse_heartbeat_seconds=0.2,
)


def make_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**BASE_OVERRIDES, **overrides})  # type: ignore[arg-type]


@dataclass
class Harness:
    app: FastAPI
    client: httpx.AsyncClient
    settings: Settings

    @property
    def session_factory(self):
        return self.app.state.session_factory

    @property
    def manager(self):
        return self.app.state.worker_manager


@asynccontextmanager
async def running_app(**overrides: Any) -> AsyncIterator[Harness]:
    app = create_app(make_settings(**overrides))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield Harness(app, client, app.state.settings)


async def make_user(h: Harness, username: str, roles: list[str], password: str = PASSWORD, **kw: Any):
    data = UserCreate(username=username, email=f"{username}@example.com", password=password,
                      role_codes=roles, **kw)
    async with h.session_factory() as session:
        return await user_service.create_user(session, h.settings, None, None, data)


async def auth_headers(h: Harness, username: str, password: str = PASSWORD) -> dict[str, str]:
    r = await h.client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_counter = itertools.count(1)


def make_event(event_id: str | None = None, event_type: str = "order.created", source: str = "shop",
               payload: dict | None = None, **kw: Any) -> dict:
    n = next(_counter)
    if payload is None:
        payload = {"order_id": f"o-{n}", "amount": 19.99, "currency": "USD"}
    return {"event_id": event_id or f"evt-{uuid.uuid4().hex[:12]}", "event_type": event_type, "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(), "payload": payload, **kw}


async def wait_until(check: Callable[[], Awaitable[bool]], timeout: float = 8.0, interval: float = 0.05) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if await check():
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(interval)


async def get_event(h: Harness, headers: dict, pk: str) -> dict:
    r = await h.client.get(f"/api/v1/events/{pk}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def wait_status(h: Harness, headers: dict, pk: str, statuses: set[str], timeout: float = 8.0) -> dict:
    last: dict = {}

    async def check() -> bool:
        nonlocal last
        last = await get_event(h, headers, pk)
        return last["status"] in statuses

    try:
        await wait_until(check, timeout)
    except AssertionError:
        raise AssertionError(f"event stuck in {last.get('status')}, wanted {statuses}: {last}") from None
    return last


async def ingest(h: Harness, key_headers: dict, **kw: Any) -> dict:
    body = make_event(**kw)
    r = await h.client.post("/api/v1/events", json=body, headers=key_headers)
    assert r.status_code in (200, 202), r.text
    return r.json()


def fresh_session():
    """An independent DB session (own engine) for inspecting state while no app is running."""
    import os
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False)()
