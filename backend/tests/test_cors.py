from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


def test_cors_preflight_for_configured_frontend_origin(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", "http://localhost:3000")
    with TestClient(create_app()) as c:
        r = c.options("/api/user/v1/login/", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:3000"
        ok = c.get("/health/live", headers={"Origin": "http://localhost:3000"})
        assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "x-request-id" in ok.headers["access-control-expose-headers"].lower()
        assert "access-control-allow-origin" not in c.get("/health/live", headers={"Origin": "http://evil.example"}).headers


def test_no_cors_headers_when_no_origins_configured(client):
    r = client.get("/health/live", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in r.headers
