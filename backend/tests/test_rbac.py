import pytest

from tests.helpers import (AUD, EV, K, P, PASSWORD, R, U, ingest, login_headers, make_user, wait_status)


def test_unauthenticated_requests_are_401(client):
    for method, path in [("get", f"{U}/v1/all/users/"), ("get", R), ("get", P), ("get", K), ("get", EV),
                         ("get", "/api/analytics/v1/overview/"), ("get", AUD), ("post", K), ("get", f"{U}/v1/me/"),
                         ("post", R), ("post", P), ("get", f"{P}1")]:
        assert getattr(client, method)(path).status_code == 401, (method, path)


@pytest.mark.parametrize("role,path,expected", [
    ("viewer", f"{U}/v1/all/users/", 403), ("viewer", K, 403), ("viewer", AUD, 403), ("viewer", R, 403),
    ("viewer", P, 403), ("viewer", EV, 200), ("viewer", "/api/analytics/v1/overview/", 200),
    ("analyst", f"{U}/v1/all/users/", 403), ("analyst", EV, 200), ("analyst", P, 403),
    ("operator", f"{U}/v1/all/users/", 403), ("operator", EV, 200), ("operator", K, 403),
    ("su", f"{U}/v1/all/users/", 200), ("su", K, 200), ("su", AUD, 200), ("su", P, 200), ("su", R, 200),
])
def test_role_matrix_get(client, role, path, expected):
    make_user("user1@example.com", role)
    assert client.get(path, headers=login_headers(client, "user1@example.com")).status_code == expected


def test_non_admins_cannot_mutate(client, viewer_headers, operator_headers, analyst_headers):
    for h in (viewer_headers, operator_headers, analyst_headers):
        assert client.post(f"{U}/v1/signup/", headers=h, json={"email": "e@e.com", "password": PASSWORD, "role_id": 1}).status_code == 403
        assert client.post(K, headers=h, json={"name": "x"}).status_code == 403
        assert client.post(R, headers=h, json={"name": "Evil", "description": "d", "code": "evil"}).status_code == 403
        assert client.post(P, headers=h, json={"name": "P", "description": "d", "code": "p_x"}).status_code == 403


def _role_id(client, headers, code):
    items = client.get(R, params={"code": code}, headers=headers).json()["result"]["data"]
    return next(r["id"] for r in items if r["code"] == code)


def test_admin_user_lifecycle(client, admin_headers):
    viewer_role = _role_id(client, admin_headers, "viewer")
    r = client.post(f"{U}/v1/signup/", headers=admin_headers, json={
        "username": "new.user", "email": "NEW@Example.com", "password": PASSWORD, "role_id": viewer_role})
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["email"] == "new@example.com" and u["role_id"] == viewer_role and "hashed_password" not in r.text
    assert client.post(f"{U}/v1/signup/", headers=admin_headers, json={
        "email": "new@example.com", "password": PASSWORD, "role_id": viewer_role}).status_code == 400
    assert client.post(f"{U}/v1/signup/", headers=admin_headers, json={
        "email": "z@example.com", "password": PASSWORD}).json()["code"] == "ROLE_REQUIRED"
    assert client.post(f"{U}/v1/signup/", headers=admin_headers, json={
        "email": "z@example.com", "password": PASSWORD, "role_id": 99999}).status_code == 404
    assert client.post(f"{U}/v1/signup/", headers=admin_headers, json={
        "email": "w@example.com", "password": "short", "role_id": viewer_role}).status_code == 422

    tok = login_headers(client, "new@example.com")
    assert client.get("/api/analytics/v1/overview/", headers=tok).status_code == 200
    operator_role = _role_id(client, admin_headers, "operator")
    up = client.patch(f"{U}/{u['id']}", headers=admin_headers, json={"role_id": operator_role, "username": "renamed"})
    assert up.status_code == 200 and up.json()["role_id"] == operator_role and up.json()["username"] == "renamed"
    assert client.get(f"{U}/v1/all/users/", params={"role_id": operator_role}, headers=admin_headers).json()["result"]["count"] == 1
    assert client.get(f"{U}/v1/all/users/", params={"search": "renam"}, headers=admin_headers).json()["result"]["count"] == 1
    assert client.get(f"{U}/{u['id']}", headers=admin_headers).status_code == 200


def test_users_can_read_and_edit_only_themselves(client, viewer_headers, operator_headers):
    me = client.get(f"{U}/v1/me/", headers=viewer_headers).json()
    other = client.get(f"{U}/v1/me/", headers=operator_headers).json()
    assert client.get(f"{U}/{me['id']}", headers=viewer_headers).status_code == 200
    assert client.get(f"{U}/{other['id']}", headers=viewer_headers).status_code == 403
    assert client.patch(f"{U}/{me['id']}", headers=viewer_headers, json={"username": "mine"}).json()["username"] == "mine"
    assert client.patch(f"{U}/{other['id']}", headers=viewer_headers, json={"username": "hacked"}).status_code == 403


def test_privilege_escalation_is_blocked(client, viewer_headers, operator_headers, admin_headers):
    me = client.get(f"{U}/v1/me/", headers=viewer_headers).json()
    su_role = _role_id(client, admin_headers, "su")
    for body in ({"is_superuser": True}, {"role_id": su_role}, {"role_id": 1}, {"is_active": False}):
        r = client.patch(f"{U}/{me['id']}", headers=viewer_headers, json=body)
        assert r.status_code == 403, (body, r.text)
    r = client.patch(f"{U}/{me['id']}", headers=viewer_headers, json={"password": "Br4nd-New-Passw0rd"})
    assert r.status_code == 403 and r.json()["code"] == "USE_CHANGE_PASSWORD"
    assert client.get(f"{U}/v1/me/", headers=viewer_headers).json()["is_superuser"] is False


def test_only_superusers_create_superusers_and_assign_su_role(client, admin_headers):
    # an "HR admin": may create users and assign roles, but is not a superuser
    ops = client.post(R, headers=admin_headers, json={"name": "UserAdmin", "description": "d", "code": "user_admin",
                                                       "permission_ids": []}).json()
    perms = {p["code"]: p["id"] for p in client.get(P, params={"limit": 100}, headers=admin_headers).json()["result"]["data"]}
    client.patch(f"{R}{ops['id']}", headers=admin_headers, json={"permission_ids": [perms["create_user"], perms["update_user"], perms["read_user"]]})
    make_user("hr@example.com", "user_admin")
    hr = login_headers(client, "hr@example.com")
    viewer_role = _role_id(client, admin_headers, "viewer")
    su_role = _role_id(client, admin_headers, "su")

    assert client.post(f"{U}/v1/signup/", headers=hr, json={"email": "s1@example.com", "password": PASSWORD,
                                                            "is_superuser": True}).status_code == 403
    assert client.post(f"{U}/v1/signup/", headers=hr, json={"email": "s2@example.com", "password": PASSWORD,
                                                            "role_id": su_role}).status_code == 403
    # a role holding permissions the HR admin lacks cannot be handed out either (read_event is not theirs)
    assert client.post(f"{U}/v1/signup/", headers=hr, json={"email": "s3@example.com", "password": PASSWORD,
                                                            "role_id": viewer_role}).json()["code"] == "CANNOT_GRANT"


def test_cannot_grant_permissions_you_do_not_hold(client, admin_headers):
    perms = {p["code"]: p["id"] for p in client.get(P, params={"limit": 100}, headers=admin_headers).json()["result"]["data"]}
    r = client.post(R, headers=admin_headers, json={"name": "RoleAdmin", "description": "d", "code": "role_admin",
                                                    "permission_ids": [perms["create_role"], perms["update_role"], perms["read_role"]]})
    assert r.status_code == 201
    make_user("ra@example.com", "role_admin")
    ra = login_headers(client, "ra@example.com")
    ok = client.post(R, headers=ra, json={"name": "Mini", "description": "d", "code": "mini", "permission_ids": [perms["read_role"]]})
    assert ok.status_code == 201
    bad = client.post(R, headers=ra, json={"name": "Big", "description": "d", "code": "big", "permission_ids": [perms["delete_user"]]})
    assert bad.status_code == 403 and bad.json()["code"] == "CANNOT_GRANT"
    mine = _role_id(client, ra, "role_admin")
    assert client.patch(f"{R}{mine}", headers=ra, json={"permission_ids": [perms["read_role"], perms["read_user"]]}).status_code == 403


def test_cannot_remove_or_demote_last_superuser_or_self(client, admin_headers):
    me = client.get(f"{U}/v1/me/", headers=admin_headers).json()
    assert client.patch(f"{U}/{me['id']}", headers=admin_headers, json={"is_active": False}).json()["code"] == "SELF_DEACTIVATION"
    assert client.patch(f"{U}/{me['id']}", headers=admin_headers, json={"is_superuser": False}).json()["code"] == "LAST_SUPERUSER"
    assert client.delete(f"{U}/{me['id']}", headers=admin_headers).json()["code"] == "SELF_DELETE"
    other = make_user("admin2@example.com", "su", superuser=True)
    h2 = login_headers(client, "admin2@example.com")
    assert client.patch(f"{U}/{me['id']}", headers=h2, json={"is_active": False}).status_code == 200  # 2 superusers: ok
    assert client.delete(f"{U}/{other}", headers=h2).json()["code"] == "SELF_DELETE"


def test_permanent_delete_is_superuser_only(client, admin_headers):
    make_user("userdel@example.com", "su")  # holds delete_user via the Super ROLE but is not a superuser
    ud = login_headers(client, "userdel@example.com")
    target = make_user("t@example.com", "viewer")
    assert client.delete(f"{U}/{target}", params={"permanent": True}, headers=ud).json()["code"] == "SUPERUSER_ONLY"
    assert client.delete(f"{U}/{target}", params={"permanent": True}, headers=admin_headers).status_code == 200
    assert client.get(f"{U}/{target}", headers=admin_headers).status_code == 404


def test_custom_role_permissions_take_effect_immediately(client, admin_headers):
    perms = {p["code"]: p["id"] for p in client.get(P, params={"limit": 100}, headers=admin_headers).json()["result"]["data"]}
    r = client.post(R, headers=admin_headers, json={"name": "Support", "description": "Help desk", "code": "support",
                                                    "permission_ids": [perms["read_event"]]})
    assert r.status_code == 201 and {p["code"] for p in r.json()["permissions"]} == {"read_event"}
    rid = r.json()["id"]
    assert client.post(R, headers=admin_headers, json={"name": "Dup", "description": "d", "code": "support"}).status_code == 400
    assert client.post(R, headers=admin_headers, json={"name": "Bad", "description": "d", "code": "bad", "permission_ids": [99999]}).status_code == 400

    make_user("sup@example.com", "support")
    sup = login_headers(client, "sup@example.com")
    assert client.get(EV, headers=sup).status_code == 200 and client.get(f"{U}/v1/all/users/", headers=sup).status_code == 403
    client.delete(f"{R}{rid}/permissions/{perms['read_event']}", headers=admin_headers)   # revoke -> next request denied
    assert client.get(EV, headers=sup).status_code == 403
    client.post(f"{R}{rid}/permissions/{perms['read_analytics']}", headers=admin_headers)
    assert client.get("/api/analytics/v1/overview/", headers=sup).status_code == 200

    assert client.delete(f"{R}{rid}", headers=admin_headers).json()["code"] == "ROLE_IN_USE"   # still assigned
    with __import__("app.database", fromlist=["x"]).SessionLocal() as db:
        from app.models import User
        db.query(User).filter(User.email == "sup@example.com").update({"role_id": None}); db.commit()
    assert client.delete(f"{R}{rid}", headers=admin_headers).status_code == 200            # soft delete
    assert client.get(f"{R}{rid}", headers=admin_headers).status_code == 404
    assert client.post(f"{R}{rid}/restore", headers=admin_headers).status_code == 200


def test_super_role_is_protected(client, admin_headers):
    su = _role_id(client, admin_headers, "su")
    assert client.patch(f"{R}{su}", headers=admin_headers, json={"permission_ids": []}).json()["code"] == "PROTECTED_ROLE"
    assert client.patch(f"{R}{su}", headers=admin_headers, json={"code": "x"}).json()["code"] == "PROTECTED_ROLE"
    assert client.delete(f"{R}{su}", headers=admin_headers).json()["code"] == "PROTECTED_ROLE"
    assert client.delete(f"{R}{su}/permissions/1", headers=admin_headers).status_code == 403


def test_direct_user_permissions(client, admin_headers):
    perms = {p["code"]: p["id"] for p in client.get(P, params={"limit": 100}, headers=admin_headers).json()["result"]["data"]}
    uid = make_user("direct@example.com", "viewer")
    h = login_headers(client, "direct@example.com")
    assert client.get(K, headers=h).status_code == 403
    r = client.post(f"{U}/{uid}/permissions/{perms['read_api_key']}", headers=admin_headers)
    assert r.status_code == 200 and [p["code"] for p in r.json()["permissions"]] == ["read_api_key"]
    assert client.get(K, headers=h).status_code == 200                       # role perms + direct perms
    assert client.get(f"{U}/v1/me/", headers=h).json()["permissions"]["read_api_key"] is True
    client.delete(f"{U}/{uid}/permissions/{perms['read_api_key']}", headers=admin_headers)
    assert client.get(K, headers=h).status_code == 403


def test_permission_crud_and_protection(client, admin_headers):
    r = client.post(P, headers=admin_headers, json={"name": "Export", "description": "d", "code": "export_x", "module_name": "Misc"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.post(P, headers=admin_headers, json={"name": "Export", "description": "d", "code": "export_x"}).status_code == 400
    assert client.patch(f"{P}{pid}", headers=admin_headers, json={"description": "new"}).json()["description"] == "new"
    assert client.get(f"{P}{pid}/with-roles", headers=admin_headers).json()["roles"] == []
    ev = next(p for p in client.get(P, params={"code": "read_event"}, headers=admin_headers).json()["result"]["data"])
    assert client.delete(f"{P}{ev['id']}", headers=admin_headers).json()["code"] == "PERMISSION_IN_USE"
    assert client.delete(f"{P}{pid}", headers=admin_headers).status_code == 200
    assert client.get(f"{P}{pid}", headers=admin_headers).status_code == 404
    assert client.post(f"{P}{pid}/restore", headers=admin_headers).status_code == 200
    assert client.delete(f"{P}{pid}", params={"permanent": True}, headers=admin_headers).status_code == 200


def test_viewer_payload_is_redacted_but_analyst_sees_it(client, key_headers, viewer_headers, analyst_headers):
    created = ingest(client, key_headers, payload={"order_id": "o1", "amount": 5, "currency": "USD", "card_last4": "4242"})
    v = wait_status(client, viewer_headers, created["id"], {"PROCESSED"})
    assert v["payload"] is None and v["metadata"] is None and v["payload_redacted"] is True
    a = wait_status(client, analyst_headers, created["id"], {"PROCESSED"})
    assert a["payload"]["card_last4"] == "4242" and a["payload_redacted"] is False
