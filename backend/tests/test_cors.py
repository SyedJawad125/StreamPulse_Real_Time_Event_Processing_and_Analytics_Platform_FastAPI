from tests.helpers import running_app


async def test_cors_preflight_for_configured_frontend_origin():
    async with running_app(cors_origins="http://localhost:3000") as h:
        r = await h.client.options("/api/v1/auth/login", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type"})
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:3000"
        ok = await h.client.get("/health/live", headers={"Origin": "http://localhost:3000"})
        assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "x-request-id" in ok.headers["access-control-expose-headers"].lower()
        evil = await h.client.get("/health/live", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in evil.headers


async def test_no_cors_headers_when_no_origins_configured(h):
    r = await h.client.get("/health/live", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in r.headers
