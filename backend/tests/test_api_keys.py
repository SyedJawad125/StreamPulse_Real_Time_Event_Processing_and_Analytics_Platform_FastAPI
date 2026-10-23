from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update

from app.models.api_key import APIKey
from tests.helpers import make_event, running_app, make_user, auth_headers

API = "/api/v1"


async def post_event(h, key, **kw):
    return await h.client.post(f"{API}/events", json=make_event(**kw), headers={"X-API-Key": key} if key else {})


async def test_key_shown_once_and_never_stored_in_plaintext(h, admin_headers):
    r = await h.client.post(f"{API}/api-keys", headers=admin_headers, json={"name": "Shop", "customer_id": "acme"})
    assert r.status_code == 201
    body = r.json()
    plaintext = body["key"]
    assert plaintext.startswith("sp_") and body["key_prefix"] in plaintext
    assert "key_hash" not in body

    listing = await h.client.get(f"{API}/api-keys", headers=admin_headers)
    assert plaintext not in listing.text and "key" not in listing.json()["items"][0]
    one = await h.client.get(f"{API}/api-keys/{body['id']}", headers=admin_headers)
    assert plaintext not in one.text

    async with h.session_factory() as s:
        row = await s.scalar(select(APIKey))
        assert plaintext not in (row.key_hash + row.key_prefix) and len(row.key_hash) == 64
        dump = (await s.execute(text("SELECT string_agg(details::text, ' ') FROM audit_logs"))).scalar() or ""
        assert plaintext not in dump  # audit trail never contains the secret


async def test_missing_invalid_and_malformed_keys_401(h, api_key):
    assert (await post_event(h, None)).status_code == 401
    assert (await post_event(h, "garbage")).status_code == 401
    forged = api_key[:-4] + "AAAA"
    r = await post_event(h, forged)
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_API_KEY"
    assert (await post_event(h, "sp_00000000_" + "A" * 43)).status_code == 401


async def test_dashboard_jwt_cannot_ingest_and_api_key_cannot_read(h, admin_headers, api_key):
    r = await h.client.post(f"{API}/events", json=make_event(), headers=admin_headers)
    assert r.status_code == 401
    assert (await h.client.get(f"{API}/events", headers={"X-API-Key": api_key})).status_code == 401
    assert (await h.client.get(f"{API}/users", headers={"X-API-Key": api_key})).status_code == 401


async def test_revoked_key_is_rejected_immediately(h, admin_headers, api_key):
    assert (await post_event(h, api_key)).status_code == 202
    kid = (await h.client.get(f"{API}/api-keys", headers=admin_headers)).json()["items"][0]["id"]
    r = await h.client.post(f"{API}/api-keys/{kid}/revoke", headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["revoked_at"]
    denied = await post_event(h, api_key)
    assert denied.status_code == 401 and denied.json()["error"]["code"] == "API_KEY_REVOKED"
    assert (await h.client.post(f"{API}/api-keys/{kid}/revoke", headers=admin_headers)).status_code == 200  # idempotent


async def test_expired_key_rejected(h, admin_headers, api_key):
    async with h.session_factory() as s:
        await s.execute(update(APIKey).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        await s.commit()
    r = await post_event(h, api_key)
    assert r.status_code == 401 and r.json()["error"]["code"] == "API_KEY_EXPIRED"
    past = await h.client.post(f"{API}/api-keys", headers=admin_headers, json={
        "name": "x", "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()})
    assert past.status_code == 422


async def test_key_without_ingest_scope_is_403(h, api_key):
    async with h.session_factory() as s:
        await s.execute(update(APIKey).values(scopes=["something.else"]))
        await s.commit()
    r = await post_event(h, api_key)
    assert r.status_code == 403 and r.json()["error"]["code"] == "INSUFFICIENT_SCOPE"


async def test_invalid_scope_rejected_at_creation(h, admin_headers):
    r = await h.client.post(f"{API}/api-keys", headers=admin_headers, json={"name": "x", "scopes": ["users.manage"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_SCOPE"


async def test_per_key_rate_limit_429_with_retry_after(h, admin_headers):
    k1 = (await h.client.post(f"{API}/api-keys", headers=admin_headers, json={"name": "limited", "rate_limit_per_minute": 3})).json()["key"]
    k2 = (await h.client.post(f"{API}/api-keys", headers=admin_headers, json={"name": "other", "rate_limit_per_minute": 3})).json()["key"]
    codes = [(await post_event(h, k1)).status_code for _ in range(5)]
    assert codes == [202, 202, 202, 429, 429]
    limited = await post_event(h, k1)
    assert limited.json()["error"]["code"] == "RATE_LIMITED" and int(limited.headers["retry-after"]) >= 1
    ok = await post_event(h, k2)  # limits are per key
    assert ok.status_code == 202 and ok.headers["x-ratelimit-limit"] == "3" and ok.headers["x-ratelimit-remaining"] == "2"


async def test_daily_quota_enforced(h, admin_headers):
    key = (await h.client.post(f"{API}/api-keys", headers=admin_headers, json={"name": "q", "daily_event_quota": 3})).json()["key"]
    assert [(await post_event(h, key)).status_code for _ in range(3)] == [202, 202, 202]
    r = await post_event(h, key)
    assert r.status_code == 429 and r.json()["error"]["code"] == "QUOTA_EXCEEDED"
    batch = await h.client.post(f"{API}/events/batch", json={"events": [make_event()]},
                                headers={"X-API-Key": key})
    assert batch.status_code == 429


async def test_update_key_and_list_filters(h, admin_headers, api_key):
    kid = (await h.client.get(f"{API}/api-keys", headers=admin_headers)).json()["items"][0]["id"]
    r = await h.client.patch(f"{API}/api-keys/{kid}", headers=admin_headers, json={"name": "renamed", "rate_limit_per_minute": 50})
    assert r.json()["name"] == "renamed" and r.json()["rate_limit_per_minute"] == 50
    await h.client.post(f"{API}/api-keys/{kid}/revoke", headers=admin_headers)
    assert (await h.client.get(f"{API}/api-keys?is_active=true", headers=admin_headers)).json()["total"] == 0
    assert (await h.client.get(f"{API}/api-keys?is_active=false", headers=admin_headers)).json()["total"] == 1
    assert (await h.client.get(f"{API}/api-keys/00000000-0000-0000-0000-000000000000", headers=admin_headers)).status_code == 404


async def test_audit_trail_records_admin_actions_without_secrets(h, admin_headers, api_key, operator_headers):
    kid = (await h.client.get(f"{API}/api-keys", headers=admin_headers)).json()["items"][0]["id"]
    await h.client.post(f"{API}/api-keys/{kid}/revoke", headers=admin_headers)
    logs = (await h.client.get(f"{API}/admin/audit-logs?limit=100", headers=admin_headers)).json()
    actions = {i["action"] for i in logs["items"]}
    assert {"api_key.created", "api_key.revoked", "auth.login", "user.created"} <= actions
    assert api_key not in str(logs) and "password" not in str(logs).lower().replace("password_changed", "")
    created = next(i for i in logs["items"] if i["action"] == "api_key.created")
    assert created["actor_username"] == "admin" and created["target_id"] == kid and created["request_id"]
    only = await h.client.get(f"{API}/admin/audit-logs?action=api_key.revoked", headers=admin_headers)
    assert only.json()["total"] == 1
    failed = await h.client.post(f"{API}/auth/login", json={"username": "admin", "password": "wrong-password-1"})
    assert failed.status_code == 401
    bad = await h.client.get(f"{API}/admin/audit-logs?success=false", headers=admin_headers)
    assert any(i["action"] == "auth.login_failed" for i in bad.json()["items"])
