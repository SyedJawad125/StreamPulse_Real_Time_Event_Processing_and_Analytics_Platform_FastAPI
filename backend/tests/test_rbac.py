import pytest

from tests.helpers import PASSWORD, auth_headers, ingest, make_user, wait_status

API = "/api/v1"


async def test_unauthenticated_requests_are_401(h):
    for method, path in [("get", "/users"), ("get", "/roles"), ("get", "/permissions"), ("get", "/api-keys"),
                         ("get", "/events"), ("get", "/analytics/overview"), ("get", "/admin/audit-logs"),
                         ("post", "/api-keys")]:
        r = await getattr(h.client, method)(API + path)
        assert r.status_code == 401, (method, path, r.status_code)


@pytest.mark.parametrize("role,path,expected", [
    ("VIEWER", "/users", 403), ("VIEWER", "/api-keys", 403), ("VIEWER", "/admin/audit-logs", 403),
    ("VIEWER", "/events", 200), ("VIEWER", "/analytics/overview", 200), ("VIEWER", "/roles", 403),
    ("ANALYST", "/users", 403), ("ANALYST", "/events", 200), ("ANALYST", "/permissions", 403),
    ("OPERATOR", "/users", 403), ("OPERATOR", "/events", 200), ("OPERATOR", "/api-keys", 403),
    ("ADMIN", "/users", 200), ("ADMIN", "/api-keys", 200), ("ADMIN", "/admin/audit-logs", 200),
    ("ADMIN", "/permissions", 200), ("ADMIN", "/roles", 200),
])
async def test_role_matrix_get(h, role, path, expected):
    await make_user(h, "user1", [role])
    r = await h.client.get(API + path, headers=await auth_headers(h, "user1"))
    assert r.status_code == expected, r.text


async def test_non_admins_cannot_mutate(h, viewer_headers, operator_headers, analyst_headers):
    for headers in (viewer_headers, operator_headers, analyst_headers):
        assert (await h.client.post(f"{API}/users", headers=headers, json={
            "username": "evil", "email": "e@e.com", "password": PASSWORD})).status_code == 403
        assert (await h.client.post(f"{API}/api-keys", headers=headers, json={"name": "x"})).status_code == 403
        assert (await h.client.post(f"{API}/roles", headers=headers, json={"name": "Evil", "code_name": "EVIL"})).status_code == 403


async def test_admin_user_lifecycle_and_role_assignment(h, admin_headers):
    r = await h.client.post(f"{API}/users", headers=admin_headers, json={
        "username": "New.User", "email": "NEW@Example.com", "password": PASSWORD, "role_codes": ["viewer"]})
    assert r.status_code == 201, r.text
    u = r.json()
    assert u["username"] == "new.user" and u["email"] == "new@example.com" and u["roles"][0]["code_name"] == "VIEWER"
    dup = await h.client.post(f"{API}/users", headers=admin_headers, json={
        "username": "new.user", "email": "other@example.com", "password": PASSWORD})
    assert dup.status_code == 409
    bad_role = await h.client.post(f"{API}/users", headers=admin_headers, json={
        "username": "zed", "email": "z@example.com", "password": PASSWORD, "role_codes": ["NOPE"]})
    assert bad_role.status_code == 422 and bad_role.json()["error"]["code"] == "UNKNOWN_ROLE"
    weak = await h.client.post(f"{API}/users", headers=admin_headers, json={
        "username": "weak1", "email": "w@example.com", "password": "short"})
    assert weak.status_code == 422

    # promote to OPERATOR; new permissions take effect on the very next request
    tok = await auth_headers(h, "new.user")
    assert (await h.client.get(f"{API}/analytics/overview", headers=tok)).status_code == 200
    up = await h.client.put(f"{API}/users/{u['id']}/roles", headers=admin_headers, json={"role_codes": ["OPERATOR"]})
    assert up.status_code == 200 and up.json()["roles"][0]["code_name"] == "OPERATOR"
    p = await h.client.patch(f"{API}/users/{u['id']}", headers=admin_headers, json={"first_name": "New"})
    assert p.json()["first_name"] == "New"
    lst = await h.client.get(f"{API}/users?role=OPERATOR&limit=5", headers=admin_headers)
    assert lst.json()["total"] == 1


async def test_cannot_deactivate_self_or_last_admin(h, admin_headers):
    me = (await h.client.get(f"{API}/auth/me", headers=admin_headers)).json()
    r = await h.client.post(f"{API}/users/{me['id']}/deactivate", headers=admin_headers)
    assert r.status_code == 403 and r.json()["error"]["code"] == "SELF_DEACTIVATION"
    r = await h.client.put(f"{API}/users/{me['id']}/roles", headers=admin_headers, json={"role_codes": ["VIEWER"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_ADMIN"
    # with a second admin, the first may be demoted by the second
    await make_user(h, "admin2", ["ADMIN"])
    h2 = await auth_headers(h, "admin2")
    assert (await h.client.post(f"{API}/users/{me['id']}/deactivate", headers=h2)).status_code == 200
    me2 = (await h.client.get(f"{API}/auth/me", headers=h2)).json()
    r = await h.client.post(f"{API}/users/{me2['id']}/deactivate", headers=h2)
    assert r.status_code == 403  # self


async def test_custom_role_and_permission_management(h, admin_headers):
    r = await h.client.post(f"{API}/roles", headers=admin_headers, json={"name": "Support", "code_name": "support"})
    assert r.status_code == 201 and r.json()["code_name"] == "SUPPORT" and r.json()["is_system"] is False
    rid = r.json()["id"]
    assert (await h.client.post(f"{API}/roles", headers=admin_headers, json={"name": "Support", "code_name": "SUPPORT"})).status_code == 409

    perms = await h.client.put(f"{API}/roles/{rid}/permissions", headers=admin_headers,
                               json={"permission_codes": ["events.read", "analytics.read"]})
    assert perms.status_code == 200 and {p["code_name"] for p in perms.json()["permissions"]} == {"events.read", "analytics.read"}
    unknown = await h.client.put(f"{API}/roles/{rid}/permissions", headers=admin_headers, json={"permission_codes": ["bogus.perm"]})
    assert unknown.status_code == 422

    await make_user(h, "sup", ["SUPPORT"])
    th = await auth_headers(h, "sup")
    assert (await h.client.get(f"{API}/events", headers=th)).status_code == 200
    assert (await h.client.get(f"{API}/users", headers=th)).status_code == 403
    # permission revoked -> next request is denied (no stale cache)
    await h.client.put(f"{API}/roles/{rid}/permissions", headers=admin_headers, json={"permission_codes": []})
    assert (await h.client.get(f"{API}/events", headers=th)).status_code == 403

    assert (await h.client.patch(f"{API}/roles/{rid}", headers=admin_headers, json={"description": "Help desk"})).json()["description"] == "Help desk"
    assert (await h.client.delete(f"{API}/roles/{rid}", headers=admin_headers)).status_code == 204
    assert (await h.client.get(f"{API}/roles/{rid}", headers=admin_headers)).status_code == 404


async def test_system_roles_are_protected(h, admin_headers):
    roles = {r["code_name"]: r for r in (await h.client.get(f"{API}/roles", headers=admin_headers)).json()}
    assert set(roles) >= {"ADMIN", "OPERATOR", "ANALYST", "VIEWER"}
    assert len(roles["ADMIN"]["permissions"]) == len((await h.client.get(f"{API}/permissions", headers=admin_headers)).json())
    assert (await h.client.delete(f"{API}/roles/{roles['VIEWER']['id']}", headers=admin_headers)).status_code == 403
    r = await h.client.put(f"{API}/roles/{roles['ADMIN']['id']}/permissions", headers=admin_headers, json={"permission_codes": []})
    assert r.status_code == 403


async def test_viewer_payload_is_redacted_but_analyst_sees_it(h, key_headers, viewer_headers, analyst_headers):
    created = await ingest(h, key_headers, payload={"order_id": "o1", "amount": 5, "currency": "USD", "card_last4": "4242"})
    v = await wait_status(h, viewer_headers, created["id"], {"PROCESSED"})
    assert v["payload"] is None and v["metadata"] is None and v["payload_redacted"] is True
    a = await wait_status(h, analyst_headers, created["id"], {"PROCESSED"})
    assert a["payload"]["card_last4"] == "4242" and a["payload_redacted"] is False
