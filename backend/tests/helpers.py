from __future__ import annotations

import itertools
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from app.database import SessionLocal
from app.models import Role, User
from app.utils import get_password_hash

PASSWORD = "Str0ng-Passw0rd!"
U = "/api/user"
R = "/api/roles/v1/role/"
P = "/api/permissions/v1/permission/"
K = "/api/api-keys/v1/api-key/"
EV = "/api/events/v1/event/"
EVB = "/api/events/v1/event/batch/"
AN = "/api/analytics/v1"
AUD = "/api/audit/v1/audit-log/"


def make_user(email: str, role_code: str | None = None, password: str = PASSWORD, superuser: bool = False,
              active: bool = True) -> int:
    with SessionLocal() as db:
        role = db.query(Role).filter(Role.code == role_code).first() if role_code else None
        user = User(username=email.split("@")[0], email=email.lower(), hashed_password=get_password_hash(password),
                    is_superuser=superuser, is_active=active, role_id=role.id if role else None)
        db.add(user)
        db.commit()
        return user.id


def login_headers(client, email: str, password: str = PASSWORD) -> dict[str, str]:
    r = client.post(f"{U}/v1/login/", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_counter = itertools.count(1)


def make_event(event_id: str | None = None, event_type: str = "order.created", source: str = "shop",
               payload: dict | None = None, **kw: Any) -> dict:
    n = next(_counter)
    if payload is None:
        payload = {"order_id": f"o-{n}", "amount": 19.99, "currency": "USD"}
    return {"event_id": event_id or f"evt-{uuid.uuid4().hex[:12]}", "event_type": event_type, "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(), "payload": payload, **kw}


def wait_until(check: Callable[[], bool], timeout: float = 8.0, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met within timeout")
        time.sleep(interval)


def get_event(client, headers: dict, pk: int) -> dict:
    r = client.get(f"{EV}{pk}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def wait_status(client, headers: dict, pk: int, statuses: set[str], timeout: float = 8.0) -> dict:
    last: dict = {}

    def check() -> bool:
        nonlocal last
        last = get_event(client, headers, pk)
        return last["status"] in statuses

    try:
        wait_until(check, timeout)
    except AssertionError:
        raise AssertionError(f"event stuck in {last.get('status')}, wanted {statuses}: {last}") from None
    return last


def ingest(client, key_headers: dict, **kw: Any) -> dict:
    r = client.post(EV, json=make_event(**kw), headers=key_headers)
    assert r.status_code in (200, 202), r.text
    return r.json()
