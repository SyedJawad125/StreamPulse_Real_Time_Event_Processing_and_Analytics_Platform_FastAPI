from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update

from app.database import SessionLocal
from app.models import APIKey
from tests.helpers import AUD, EV, EVB, K, make_event


def post_event(client, key, **kw):
    return client.post(EV, json=make_event(**kw), headers={"X-API-Key": key} if key else {})


def test_key_shown_once_and_never_stored_in_plaintext(client, admin_headers):
    r = client.post(K, headers=admin_headers, json={"name": "Shop", "customer_id": "acme"})
    assert r.status_code == 201
    body = r.json()
    plaintext = body["key"]
    assert plaintext.startswith("sp_") and body["key_prefix"] in plaintext and "key_hash" not in body
    listing = client.get(K, headers=admin_headers)
    assert plaintext not in listing.text and "key" not in listing.json()["result"]["data"][0]
    assert plaintext not in client.get(f"{K}{body['id']}", headers=admin_headers).text
    with SessionLocal() as db:
        row = db.scalar(select(APIKey))
        assert plaintext not in (row.key_hash + row.key_prefix) and len(row.key_hash) == 64
        assert row.created_by_user_id is not None
        dump = db.execute(text("SELECT string_agg(details::text, ' ') FROM audit_logs")).scalar() or ""
        assert plaintext not in dump  # the audit trail never contains the secret


def test_missing_invalid_and_malformed_keys_401(client, api_key):
    assert post_event(client, None).status_code == 401
    assert post_event(client, "garbage").status_code == 401
    r = post_event(client, api_key[:-4] + "AAAA")
    assert r.status_code == 401 and r.json()["code"] == "INVALID_API_KEY"
    assert post_event(client, "sp_00000000_" + "A" * 43).status_code == 401


def test_dashboard_jwt_cannot_ingest_and_api_key_cannot_read(client, admin_headers, api_key):
    assert client.post(EV, json=make_event(), headers=admin_headers).status_code == 401
    assert client.get(EV, headers={"X-API-Key": api_key}).status_code == 401
    assert client.get(K, headers={"X-API-Key": api_key}).status_code == 401


def test_revoked_key_is_rejected_immediately(client, admin_headers, api_key):
    assert post_event(client, api_key).status_code == 202
    kid = client.get(K, headers=admin_headers).json()["result"]["data"][0]["id"]
    r = client.post(f"{K}{kid}/revoke", headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["revoked_at"]
    denied = post_event(client, api_key)
    assert denied.status_code == 401 and denied.json()["code"] == "API_KEY_REVOKED"
    assert client.post(f"{K}{kid}/revoke", headers=admin_headers).status_code == 200  # idempotent


def test_deleted_key_is_unusable_and_hidden(client, admin_headers, api_key):
    kid = client.get(K, headers=admin_headers).json()["result"]["data"][0]["id"]
    assert client.delete(f"{K}{kid}", headers=admin_headers).status_code == 200
    assert post_event(client, api_key).status_code == 401
    assert client.get(K, headers=admin_headers).json()["result"]["count"] == 0
    assert client.get(K, params={"include_deleted": True}, headers=admin_headers).json()["result"]["count"] == 1
    assert client.get(f"{K}{kid}", headers=admin_headers).status_code == 404


def test_expired_key_rejected(client, admin_headers, api_key):
    with SessionLocal() as db:
        db.execute(update(APIKey).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()
    r = post_event(client, api_key)
    assert r.status_code == 401 and r.json()["code"] == "API_KEY_EXPIRED"
    past = client.post(K, headers=admin_headers, json={"name": "x", "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()})
    assert past.status_code == 422


def test_key_without_ingest_scope_is_403(client, api_key):
    with SessionLocal() as db:
        db.execute(update(APIKey).values(scopes=["something.else"]))
        db.commit()
    r = post_event(client, api_key)
    assert r.status_code == 403 and r.json()["code"] == "INSUFFICIENT_SCOPE"


def test_invalid_scope_rejected_at_creation(client, admin_headers):
    r = client.post(K, headers=admin_headers, json={"name": "x", "scopes": ["delete_user"]})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_SCOPE"


def test_per_key_rate_limit_429_with_retry_after(client, admin_headers):
    k1 = client.post(K, headers=admin_headers, json={"name": "limited", "rate_limit_per_minute": 3}).json()["key"]
    k2 = client.post(K, headers=admin_headers, json={"name": "other", "rate_limit_per_minute": 3}).json()["key"]
    assert [post_event(client, k1).status_code for _ in range(5)] == [202, 202, 202, 429, 429]
    limited = post_event(client, k1)
    assert limited.json()["code"] == "RATE_LIMITED" and int(limited.headers["retry-after"]) >= 1
    ok = post_event(client, k2)  # limits are per key
    assert ok.status_code == 202 and ok.headers["x-ratelimit-limit"] == "3" and ok.headers["x-ratelimit-remaining"] == "2"


def test_daily_quota_enforced(client, admin_headers):
    key = client.post(K, headers=admin_headers, json={"name": "q", "daily_event_quota": 3}).json()["key"]
    assert [post_event(client, key).status_code for _ in range(3)] == [202, 202, 202]
    r = post_event(client, key)
    assert r.status_code == 429 and r.json()["code"] == "QUOTA_EXCEEDED"
    assert client.post(EVB, json={"events": [make_event()]}, headers={"X-API-Key": key}).status_code == 429


def test_update_key_and_list_filters(client, admin_headers, api_key):
    kid = client.get(K, headers=admin_headers).json()["result"]["data"][0]["id"]
    r = client.patch(f"{K}{kid}", headers=admin_headers, json={"name": "renamed", "rate_limit_per_minute": 50})
    assert r.json()["name"] == "renamed" and r.json()["rate_limit_per_minute"] == 50 and r.json()["updated_by_user_id"]
    client.post(f"{K}{kid}/revoke", headers=admin_headers)
    assert client.get(K, params={"is_active": True}, headers=admin_headers).json()["result"]["count"] == 0
    assert client.get(K, params={"is_active": False}, headers=admin_headers).json()["result"]["count"] == 1
    assert client.get(f"{K}999999", headers=admin_headers).status_code == 404


def test_audit_trail_records_admin_actions_without_secrets(client, admin_headers, api_key):
    kid = client.get(K, headers=admin_headers).json()["result"]["data"][0]["id"]
    client.post(f"{K}{kid}/revoke", headers=admin_headers)
    logs = client.get(AUD, params={"limit": 100}, headers=admin_headers).json()["result"]
    actions = {i["action"] for i in logs["data"]}
    assert {"api_key.created", "api_key.revoked", "auth.login"} <= actions
    assert api_key not in str(logs) and "hashed_password" not in str(logs)
    created = next(i for i in logs["data"] if i["action"] == "api_key.created")
    assert created["actor_email"] == "admin@example.com" and created["target_id"] == str(kid) and created["request_id"]
    assert client.get(AUD, params={"action": "api_key.revoked"}, headers=admin_headers).json()["result"]["count"] == 1
    client.post("/api/user/v1/login/", json={"email": "admin@example.com", "password": "wrong-password-1"})
    bad = client.get(AUD, params={"success": False}, headers=admin_headers).json()["result"]["data"]
    assert any(i["action"] == "auth.login_failed" for i in bad)
