import httpx
from fastapi.testclient import TestClient

from app import database
from app.main import app
from tests.helpers import U


def test_live(client):
    r = client.get("/health/live")
    assert r.status_code == 200 and r.json() == {"status": "alive"}


def test_ready_and_health_report_real_state(client):
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"database": "ok", "workers": "ok", "queue": "ok"}
    r = client.get("/health")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert body["worker"]["workers_alive"] == body["worker"]["workers_configured"] == 2
    text = r.text.lower()
    assert "password" not in text and "postgresql" not in text and "streampulse_app" not in text


def test_ready_fails_when_database_down(client, monkeypatch):
    monkeypatch.setattr(database, "check_database", lambda *a, **k: False)
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "down"
    assert client.get("/health").status_code == 503
    assert client.get("/health/live").status_code == 200  # liveness unaffected


def test_ready_fails_when_workers_stopped(client, manager):
    manager.stop()
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["workers"] == "down"


def test_database_connectivity():
    assert database.check_database() is True


def test_error_shape_and_request_id(client):
    r = client.get("/api/nope", headers={"X-Request-ID": "my-request-id-123"})
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "NOT_FOUND" and body["request_id"] == "my-request-id-123" and "detail" in body
    assert r.headers["x-request-id"] == "my-request-id-123"


def test_request_id_generated_when_missing_or_invalid(client):
    assert len(client.get("/health/live").headers["x-request-id"]) >= 8
    r = client.get("/health/live", headers={"X-Request-ID": "bad id with spaces\t"})
    assert r.headers["x-request-id"] != "bad id with spaces\t"


def test_validation_errors_do_not_echo_input(client):
    r = client.post(f"{U}/v1/login/", json={"email": "not-an-email", "password": "SuperSecret123!"})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert "SuperSecret123!" not in r.text and "not-an-email" not in r.text


def test_unhandled_exception_is_hidden(client):
    @app.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR" and "secret internal detail" not in r.text


def test_graceful_shutdown_stops_workers():
    with TestClient(app) as c:
        manager = c.app.state.worker_manager
        assert manager.status()["workers_alive"] == 2
    st = manager.status()
    assert st["running"] is False and st["workers_alive"] == 0 and st["sweeper_alive"] is False
