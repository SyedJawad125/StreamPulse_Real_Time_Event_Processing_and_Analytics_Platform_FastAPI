from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, update

from app.models.user import User
from tests.helpers import PASSWORD, auth_headers, make_user


async def login(h, username="admin", password=PASSWORD):
    return await h.client.post("/api/v1/auth/login", json={"username": username, "password": password})


async def test_login_me_and_permissions(h):
    await make_user(h, "admin", ["ADMIN"])
    r = await login(h)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"]["username"] == "admin"
    assert "password_hash" not in r.text
    me = await h.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and "users.manage" in me.json()["permissions"]
    assert me.json()["roles"][0]["code_name"] == "ADMIN"


async def test_login_with_email_case_insensitive(h):
    await make_user(h, "alice", ["VIEWER"])
    assert (await login(h, "ALICE@example.com")).status_code == 200


async def test_wrong_password_and_unknown_user_look_identical(h):
    await make_user(h, "admin", ["ADMIN"])
    a = await login(h, "admin", "wrong-password-1")
    b = await login(h, "ghost", "wrong-password-1")
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["code"] == b.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


async def test_missing_malformed_and_tampered_tokens(h, admin_headers):
    assert (await h.client.get("/api/v1/auth/me")).status_code == 401
    assert (await h.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"})).status_code == 401
    tok = admin_headers["Authorization"].split()[1]
    assert (await h.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok[:-3]}abc"})).status_code == 401


async def test_expired_token_rejected(h, admin_headers):
    tok = admin_headers["Authorization"].split()[1]
    claims = jwt.decode(tok, options={"verify_signature": False})
    claims["exp"] = int(datetime.now(timezone.utc).timestamp()) - 5
    expired = jwt.encode(claims, h.settings.secret_key.get_secret_value(), algorithm="HS256")
    r = await h.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_logout_revokes_token(h, admin_headers):
    assert (await h.client.post("/api/v1/auth/logout", headers=admin_headers)).status_code == 200
    r = await h.client.get("/api/v1/auth/me", headers=admin_headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_REVOKED"


async def test_change_password_invalidates_old_tokens(h, admin_headers):
    new = "An0ther-Str0ng-Pass!"
    bad = await h.client.post("/api/v1/auth/change-password", headers=admin_headers,
                              json={"current_password": "nope-nope-123", "new_password": new})
    assert bad.status_code == 401
    weak = await h.client.post("/api/v1/auth/change-password", headers=admin_headers,
                               json={"current_password": PASSWORD, "new_password": "short1"})
    assert weak.status_code == 422
    ok = await h.client.post("/api/v1/auth/change-password", headers=admin_headers,
                             json={"current_password": PASSWORD, "new_password": new})
    assert ok.status_code == 200
    assert (await h.client.get("/api/v1/auth/me", headers=admin_headers)).status_code == 401  # old token dead
    fresh = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (await h.client.get("/api/v1/auth/me", headers=fresh)).status_code == 200
    assert (await login(h, "admin", PASSWORD)).status_code == 401
    assert (await login(h, "admin", new)).status_code == 200


async def test_stored_password_is_argon2id_not_plaintext(h):
    await make_user(h, "admin", ["ADMIN"])
    async with h.session_factory() as s:
        u = await s.scalar(select(User).where(User.username == "admin"))
    assert u.password_hash.startswith("$argon2id$") and PASSWORD not in u.password_hash


async def test_account_lockout_after_repeated_failures(h):
    await make_user(h, "admin", ["ADMIN"])
    for _ in range(h.settings.login_max_failed_attempts):
        assert (await login(h, "admin", "wrong-password-1")).status_code == 401
    locked = await login(h, "admin", PASSWORD)  # even the right password is refused while locked
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert int(locked.headers["retry-after"]) > 0
    async with h.session_factory() as s:  # simulate lock expiry
        await s.execute(update(User).where(User.username == "admin").values(locked_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
        await s.commit()
    assert (await login(h, "admin", PASSWORD)).status_code == 200


async def test_ip_login_throttle():
    from tests.helpers import running_app
    async with running_app(login_ip_limit_per_minute=3) as h:
        codes = [(await login(h, "nobody", "wrong-password-1")).status_code for _ in range(5)]
        assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


async def test_inactive_user_cannot_login_and_existing_token_dies(h, admin_headers):
    await make_user(h, "bob", ["VIEWER"])
    bob = await auth_headers(h, "bob")
    users = (await h.client.get("/api/v1/users?q=bob", headers=admin_headers)).json()["items"]
    r = await h.client.post(f"/api/v1/users/{users[0]['id']}/deactivate", headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert (await h.client.get("/api/v1/auth/me", headers=bob)).status_code == 401  # effective immediately
    d = await login(h, "bob")
    assert d.status_code == 403 and d.json()["error"]["code"] == "ACCOUNT_DISABLED"
    wrong = await login(h, "bob", "wrong-password-1")
    assert wrong.status_code == 401  # no account-state leak without the right password
    await h.client.post(f"/api/v1/users/{users[0]['id']}/activate", headers=admin_headers)
    assert (await login(h, "bob")).status_code == 200


async def test_oauth2_form_token_endpoint_for_swagger(h):
    await make_user(h, "admin", ["ADMIN"])
    r = await h.client.post("/api/v1/auth/token", data={"username": "admin", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["access_token"]


async def test_no_public_registration_endpoint(h):
    for path in ("/api/v1/auth/register", "/api/v1/auth/signup", "/api/v1/register"):
        assert (await h.client.post(path, json={"username": "x"})).status_code in (404, 405)
    assert (await h.client.post("/api/v1/users", json={"username": "evil", "email": "e@e.com", "password": "Passw0rd-Passw0rd"})).status_code == 401
