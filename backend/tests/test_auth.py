from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, update

from app.config import settings
from app.database import SessionLocal
from app.models import User
from tests.helpers import PASSWORD, U, login_headers, make_user


def login(client, email="admin@example.com", password=PASSWORD):
    return client.post(f"{U}/v1/login/", json={"email": email, "password": password})


def test_login_shape_me_and_permissions(client):
    make_user("admin@example.com", "su", superuser=True)
    r = login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["message"] == "Login successful" and body["token_type"] == "bearer"
    assert body["user"]["email"] == "admin@example.com" and body["user"]["is_superuser"] is True
    assert body["user"]["role_name"] == "Super" and body["permissions"]["read_event"] is True
    assert "hashed_password" not in r.text
    me = client.get(f"{U}/v1/me/", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["permissions"]["create_user"] is True and me.json()["role_name"] == "Super"


def test_login_is_case_insensitive_and_regular_user_permissions(client):
    make_user("viewer@example.com", "viewer")
    r = login(client, "VIEWER@Example.com")
    perms = r.json()["permissions"]
    assert r.status_code == 200 and perms["read_event"] is True and perms["create_user"] is False
    assert set(perms) >= {"read_role", "reprocess_event", "read_audit_log"}  # every permission is listed (True/False)


def test_wrong_password_and_unknown_user_look_identical(client):
    make_user("admin@example.com", "su", superuser=True)
    a = login(client, "admin@example.com", "wrong-password-1")
    b = login(client, "ghost@example.com", "wrong-password-1")
    assert a.status_code == b.status_code == 401
    assert a.json()["code"] == b.json()["code"] == "INVALID_CREDENTIALS" and a.json()["detail"] == b.json()["detail"]


def test_missing_malformed_and_tampered_tokens(client, admin_headers):
    assert client.get(f"{U}/v1/me/").status_code == 401
    assert client.get(f"{U}/v1/me/", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    tok = admin_headers["Authorization"].split()[1]
    assert client.get(f"{U}/v1/me/", headers={"Authorization": f"Bearer {tok[:-3]}abc"}).status_code == 401


def test_expired_token_rejected(client, admin_headers):
    tok = admin_headers["Authorization"].split()[1]
    claims = jwt.decode(tok, options={"verify_signature": False})
    claims["exp"] = int(datetime.now(timezone.utc).timestamp()) - 5
    expired = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    r = client.get(f"{U}/v1/me/", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRED"


def test_logout_revokes_access_token(client, admin_headers):
    assert client.post(f"{U}/v1/logout/", headers=admin_headers).status_code == 200
    r = client.get(f"{U}/v1/me/", headers=admin_headers)
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_REVOKED"


def test_refresh_rotation_and_token_type_separation(client):
    make_user("admin@example.com", "su", superuser=True)
    body = login(client).json()
    access, refresh = body["access_token"], body["refresh_token"]
    # an access token can't refresh; a refresh token can't call the API
    assert client.post(f"{U}/v1/refresh/", json={"refresh_token": access}).status_code == 401
    assert client.get(f"{U}/v1/me/", headers={"Authorization": f"Bearer {refresh}"}).status_code == 401
    r = client.post(f"{U}/v1/refresh/", json={"refresh_token": refresh})
    assert r.status_code == 200 and r.json()["access_token"] and r.json()["refresh_token"] != refresh
    assert client.get(f"{U}/v1/me/", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200
    again = client.post(f"{U}/v1/refresh/", json={"refresh_token": refresh})  # old refresh token: single use
    assert again.status_code == 401 and again.json()["code"] == "TOKEN_REVOKED"


def test_logout_can_revoke_refresh_token_too(client):
    make_user("admin@example.com", "su", superuser=True)
    body = login(client).json()
    h = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.post(f"{U}/v1/logout/", json={"refresh_token": body["refresh_token"]}, headers=h).status_code == 200
    assert client.post(f"{U}/v1/refresh/", json={"refresh_token": body["refresh_token"]}).status_code == 401


def test_change_password_invalidates_old_tokens(client, admin_headers):
    new = "An0ther-Str0ng-Pass!"
    assert client.post(f"{U}/v1/change-password/", headers=admin_headers,
                       json={"current_password": "nope-nope-123", "new_password": new}).status_code == 401
    assert client.post(f"{U}/v1/change-password/", headers=admin_headers,
                       json={"current_password": PASSWORD, "new_password": "short1"}).status_code == 422
    ok = client.post(f"{U}/v1/change-password/", headers=admin_headers,
                     json={"current_password": PASSWORD, "new_password": new})
    assert ok.status_code == 200
    assert client.get(f"{U}/v1/me/", headers=admin_headers).status_code == 401  # old token dead
    assert client.get(f"{U}/v1/me/", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}).status_code == 200
    assert login(client, password=PASSWORD).status_code == 401 and login(client, password=new).status_code == 200


def test_stored_password_is_argon2id(client):
    make_user("admin@example.com", "su", superuser=True)
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@example.com"))
    assert u.hashed_password.startswith("$argon2id$") and PASSWORD not in u.hashed_password


def test_account_lockout_after_repeated_failures(client):
    make_user("admin@example.com", "su", superuser=True)
    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        assert login(client, password="wrong-password-1").status_code == 401
    locked = login(client)  # even the right password is refused while locked
    assert locked.status_code == 429 and locked.json()["code"] == "ACCOUNT_LOCKED" and int(locked.headers["retry-after"]) > 0
    with SessionLocal() as db:  # simulate expiry of the lock
        db.execute(update(User).values(locked_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()
    assert login(client).status_code == 200


def test_ip_login_throttle(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_IP_LIMIT_PER_MINUTE", 3)
    client.app.state.rate_limiter.reset("login-ip:testclient")
    codes = [login(client, "nobody@example.com", "wrong-password-1").status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_inactive_user_cannot_login_and_existing_token_dies(client, admin_headers):
    uid = make_user("bob@example.com", "viewer")
    bob = login_headers(client, "bob@example.com")
    r = client.patch(f"{U}/{uid}", json={"is_active": False}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get(f"{U}/v1/me/", headers=bob).status_code == 401  # effective immediately
    d = login(client, "bob@example.com")
    assert d.status_code == 403 and d.json()["code"] == "ACCOUNT_DISABLED"
    assert login(client, "bob@example.com", "wrong-password-1").status_code == 401  # no state leak without the password
    client.patch(f"{U}/{uid}", json={"is_active": True}, headers=admin_headers)
    assert login(client, "bob@example.com").status_code == 200


def test_deleted_user_token_dies_and_cannot_login(client, admin_headers):
    uid = make_user("bob@example.com", "viewer")
    bob = login_headers(client, "bob@example.com")
    assert client.delete(f"{U}/{uid}", headers=admin_headers).status_code == 200
    assert client.get(f"{U}/v1/me/", headers=bob).status_code == 401
    assert login(client, "bob@example.com").status_code == 401
    assert client.post(f"{U}/{uid}/restore", headers=admin_headers).status_code == 200
    assert login(client, "bob@example.com").status_code == 200


def test_oauth2_form_token_endpoint_for_swagger(client):
    make_user("admin@example.com", "su", superuser=True)
    r = client.post(f"{U}/v1/token/", data={"username": "admin@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["access_token"]


def test_user_without_role_cannot_log_in(client):
    make_user("norole@example.com", None)
    r = login(client, "norole@example.com")
    assert r.status_code == 403 and r.json()["code"] == "NO_ROLE_ASSIGNED"


def test_signup_is_not_public(client, viewer_headers):
    body = {"email": "evil@example.com", "password": "Passw0rd-Passw0rd", "is_superuser": True}
    assert client.post(f"{U}/v1/signup/", json=body).status_code == 401           # anonymous
    assert client.post(f"{U}/v1/signup/", json=body, headers=viewer_headers).status_code == 403  # no create_user
