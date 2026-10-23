from unittest.mock import AsyncMock, patch

from tests.helpers import running_app


async def test_live(h):
    r = await h.client.get("/health/live")
    assert r.status_code == 200 and r.json() == {"status": "alive"}


async def test_ready_and_health_report_real_state(h):
    r = await h.client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["checks"] == {"database": "ok", "workers": "ok", "queue": "ok"}

    r = await h.client.get("/health")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert body["worker"]["workers_alive"] == h.settings.event_worker_concurrency
    assert body["worker"]["queue_capacity"] == h.settings.event_queue_maxsize
    text = r.text.lower()
    assert "password" not in text and "streampulse_app" not in text and "postgresql" not in text  # no secrets/DSN


async def test_ready_fails_when_database_down(h):
    with patch("app.api.v1.health.check_database", AsyncMock(return_value=False)):
        r = await h.client.get("/health/ready")
        assert r.status_code == 503 and r.json()["checks"]["database"] == "down"
        assert (await h.client.get("/health")).status_code == 503
        assert (await h.client.get("/health/live")).status_code == 200  # liveness unaffected


async def test_ready_fails_when_workers_stopped(h):
    await h.manager.stop()
    r = await h.client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["workers"] == "down"


async def test_database_connectivity(h):
    from sqlalchemy import text
    async with h.session_factory() as s:
        assert (await s.execute(text("SELECT 1"))).scalar() == 1


async def test_error_shape_and_request_id(h):
    r = await h.client.get("/api/v1/nope", headers={"X-Request-ID": "my-request-id-123"})
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "NOT_FOUND" and err["request_id"] == "my-request-id-123"
    assert r.headers["x-request-id"] == "my-request-id-123"


async def test_request_id_generated_when_missing_or_invalid(h):
    r = await h.client.get("/health/live")
    assert len(r.headers["x-request-id"]) >= 8
    r2 = await h.client.get("/health/live", headers={"X-Request-ID": "bad id with spaces\t"})
    assert r2.headers["x-request-id"] != "bad id with spaces\t"


async def test_validation_errors_do_not_echo_input(h):
    r = await h.client.post("/api/v1/auth/login", json={"username": "x", "password": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = await h.client.post("/api/v1/auth/login", json={"username": "x", "password": "SuperSecret123!", "bogus": 1, "extra": [1]})
    assert "SuperSecret123!" not in r.text


async def test_unhandled_exception_is_hidden(h):
    @h.app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    # raise_app_exceptions=False so the 500 handler response is returned like in production
    import httpx
    transport = httpx.ASGITransport(app=h.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR" and "secret internal detail" not in r.text


async def test_graceful_shutdown_stops_workers():
    async with running_app() as h:
        manager = h.manager
        assert manager.status()["workers_alive"] == 2
    st = manager.status()
    assert st["running"] is False and st["workers_alive"] == 0 and st["sweeper_alive"] is False
