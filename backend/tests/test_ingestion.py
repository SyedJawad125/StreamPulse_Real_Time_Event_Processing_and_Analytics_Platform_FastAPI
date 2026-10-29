from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.main import create_app
from app.models import Event
from tests.helpers import AN, EV, EVB, K, login_headers, make_event, make_user, wait_status


def count_events(**where) -> int:
    with SessionLocal() as db:
        q = select(func.count(Event.id))
        for k, v in where.items():
            q = q.where(getattr(Event, k) == v)
        return db.scalar(q)


def test_single_event_accepted_not_reported_as_processed(client, key_headers, admin_headers):
    body = make_event(event_id="order-1001")
    r = client.post(EV, json=body, headers=key_headers)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "accepted" and data["event_id"] == "order-1001" and isinstance(data["id"], int)
    assert data["processing_status"] in ("RECEIVED", "QUEUED")  # never PROCESSED at accept time
    done = wait_status(client, admin_headers, data["id"], {"PROCESSED"})
    assert done["processing_duration_ms"] is not None and done["completed_at"] and done["retry_count"] == 0
    assert done["payload"]["order_id"] == body["payload"]["order_id"]


def test_duplicate_event_is_detected_and_counted(client, key_headers, admin_headers):
    body = make_event(event_id="dup-1")
    codes = [client.post(EV, json=body, headers=key_headers) for _ in range(3)]
    assert [c.status_code for c in codes] == [202, 200, 200]
    assert codes[1].json()["status"] == "duplicate" and codes[1].json()["id"] == codes[0].json()["id"]
    assert count_events() == 1
    ev = client.get(EV, params={"event_id": "dup-1"}, headers=admin_headers).json()["result"]["data"][0]
    assert ev["duplicate_count"] == 2
    ov = client.get(f"{AN}/overview/", headers=admin_headers).json()
    assert ov["duplicate_submissions"] == 2 and ov["total_received"] == 1


def test_concurrent_duplicate_submissions_create_exactly_one_row(client, key_headers):
    body = make_event(event_id="race-1")
    with ThreadPoolExecutor(16) as pool:
        rs = list(pool.map(lambda _: client.post(EV, json=body, headers=key_headers), range(25)))
    codes = sorted(r.status_code for r in rs)
    assert codes.count(202) == 1 and codes.count(200) == 24
    assert len({r.json()["id"] for r in rs}) == 1
    assert count_events(event_id="race-1") == 1


def test_concurrent_overlapping_batches_do_not_deadlock(client, key_headers):
    ids = [f"ov-{i}" for i in range(10)]
    batches = [{"events": [make_event(event_id=i) for i in (ids if n % 2 == 0 else list(reversed(ids)))]} for n in range(8)]
    with ThreadPoolExecutor(8) as pool:
        rs = list(pool.map(lambda b: client.post(EVB, json=b, headers=key_headers), batches))
    assert all(r.status_code == 202 for r in rs), [r.text for r in rs if r.status_code != 202]
    assert sum(r.json()["accepted"] for r in rs) == 10  # each id accepted exactly once across all requests
    assert sum(r.json()["duplicates"] for r in rs) == 70
    assert count_events() == 10


def test_batch_reports_accepted_rejected_duplicates(client, key_headers):
    client.post(EV, json=make_event(event_id="pre-existing"), headers=key_headers)
    batch = {"events": [
        make_event(event_id="b-1"),
        make_event(event_id="b-2", event_type="order.created", payload={"order_id": "x"}),  # missing amount/currency
        make_event(event_id="pre-existing"),
        make_event(event_id="b-1"),  # repeated inside the batch
        {"event_id": "b-bad", "source": "x"},  # structurally invalid
        42,  # not even an object
        make_event(event_id="b-3", schema_version="7.0"),
        make_event(event_id="b-4", event_type="custom.thing", payload={"anything": [1, 2, 3]}),
    ]}
    r = client.post(EVB, json=batch, headers=key_headers)
    assert r.status_code == 202
    d = r.json()
    assert (d["accepted"], d["duplicates"], d["rejected"]) == (2, 2, 4)
    by = {x["index"]: x for x in d["results"]}
    assert [by[i]["status"] for i in range(8)] == [
        "accepted", "rejected", "duplicate", "duplicate", "rejected", "rejected", "rejected", "accepted"]
    assert by[1]["code"] == "invalid_payload" and by[6]["code"] == "unsupported_schema_version"
    assert by[3]["code"] == "duplicate_in_batch" and by[0]["id"]
    assert count_events() == 3


def test_batch_shape_and_limits(client, key_headers, monkeypatch):
    assert client.post(EVB, json={"events": []}, headers=key_headers).status_code == 422
    assert client.post(EVB, json={"nope": 1}, headers=key_headers).status_code == 422
    monkeypatch.setattr(settings, "MAX_BATCH_SIZE", 3)
    r = client.post(EVB, json={"events": [make_event() for _ in range(4)]}, headers=key_headers)
    assert r.status_code == 413 and r.json()["code"] == "BATCH_TOO_LARGE"
    ok = client.post(EVB, json={"events": [make_event() for _ in range(3)]}, headers=key_headers)
    assert ok.status_code == 202 and ok.json()["accepted"] == 3


def test_request_body_size_limit_413(api_key, monkeypatch):
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 2000)
    with TestClient(create_app()) as c:  # the middleware captures the limit when the app is created
        k = {"X-API-Key": api_key}
        big = make_event(payload={"blob": "x" * 5000, "order_id": "1", "amount": 1, "currency": "USD"})
        r = c.post(EV, json=big, headers=k)
        assert r.status_code == 413 and r.json()["code"] == "PAYLOAD_TOO_LARGE"

        def chunked():  # no Content-Length: enforced on the streamed bytes
            for _ in range(10):
                yield b'{"x":"' + b"a" * 500 + b'"}'

        r2 = c.post(EV, content=chunked(), headers={**k, "content-type": "application/json"})
        assert r2.status_code == 413
        assert c.post(EV, json=make_event(), headers=k).status_code == 202  # normal requests still fine


def test_event_payload_too_large_413(client, key_headers):
    big = make_event(event_type="custom.big", payload={"blob": "x" * (settings.MAX_PAYLOAD_BYTES + 10)})
    r = client.post(EV, json=big, headers=key_headers)
    assert r.status_code == 413 and r.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert count_events() == 0


def test_invalid_events_never_reach_the_worker(client, key_headers):
    base = make_event()
    cases = {
        "missing field": {k: v for k, v in base.items() if k != "event_type"},
        "bad event_id chars": {**base, "event_id": "has spaces!"},
        "bad event_type": {**base, "event_type": "Order Created"},
        "empty event_id": {**base, "event_id": ""},
        "extra field": {**base, "surprise": 1},
        "naive timestamp": {**base, "timestamp": "2026-01-01T10:00:00"},
        "garbage timestamp": {**base, "timestamp": "yesterday"},
        "payload not object": {**base, "payload": [1, 2]},
    }
    for name, body in cases.items():
        assert client.post(EV, json=body, headers=key_headers).status_code == 422, name
    assert count_events() == 0


def test_timestamp_rules(client, key_headers):
    future = make_event(timestamp=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    r = client.post(EV, json=future, headers=key_headers)
    assert r.status_code == 422 and r.json()["code"] == "INVALID_TIMESTAMP"
    assert client.post(EV, json=make_event(timestamp=(datetime.now(timezone.utc) - timedelta(days=800)).isoformat()), headers=key_headers).status_code == 422
    assert client.post(EV, json=make_event(timestamp=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()), headers=key_headers).status_code == 202
    assert client.post(EV, json=make_event(timestamp="2026-10-01T12:00:00+05:00"), headers=key_headers).status_code == 202


def test_unsupported_schema_version(client, key_headers):
    r = client.post(EV, json=make_event(schema_version="2.0"), headers=key_headers)
    assert r.status_code == 422 and r.json()["code"] == "UNSUPPORTED_SCHEMA_VERSION" and "1.0" in r.json()["detail"]


def test_event_specific_payload_requirements(client, key_headers):
    bad = [
        make_event(event_type="order.created", payload={"order_id": "1", "amount": -5, "currency": "USD"}),
        make_event(event_type="order.created", payload={"order_id": "1", "amount": "ten", "currency": "USD"}),
        make_event(event_type="payment.succeeded", payload={"payment_id": "p", "amount": 5, "currency": "DOLLARS"}),
        make_event(event_type="user.activity", payload={"user_id": "u"}),
        make_event(event_type="app.error", payload={"service": "api"}),
        make_event(event_type="service.health", payload={"service": "db", "status": "sleepy"}),
    ]
    for body in bad:
        r = client.post(EV, json=body, headers=key_headers)
        assert r.status_code == 422 and r.json()["code"] == "INVALID_PAYLOAD", (body, r.text)
    good = [
        make_event(event_type="user.activity", payload={"user_id": "u", "action": "login"}),
        make_event(event_type="app.error", payload={"service": "api", "message": "boom"}),
        make_event(event_type="service.health", payload={"service": "db", "status": "degraded"}),
        make_event(event_type="payment.failed", payload={"payment_id": "p", "amount": 0, "currency": "eur"}),
    ]
    assert all(client.post(EV, json=b, headers=key_headers).status_code == 202 for b in good)


def test_nul_character_and_deep_nesting_rejected(client, key_headers):
    assert client.post(EV, json=make_event(event_type="custom.x", payload={"text": "a\u0000b"}), headers=key_headers).status_code == 422
    deep: dict = {}
    cur = deep
    for _ in range(15):
        cur["n"] = {}
        cur = cur["n"]
    r = client.post(EV, json=make_event(event_type="custom.x", payload=deep), headers=key_headers)
    assert r.status_code == 422 and r.json()["code"] == "INVALID_PAYLOAD"


def test_tenant_isolation(client, admin_headers):
    key = client.post(K, headers=admin_headers, json={"name": "acme", "customer_id": "acme"}).json()["key"]
    kh = {"X-API-Key": key}
    r = client.post(EV, json=make_event(customer_id="globex"), headers=kh)
    assert r.status_code == 403 and r.json()["code"] == "CUSTOMER_MISMATCH" and count_events() == 0
    assert client.post(EV, json=make_event(event_id="t-1", customer_id="acme"), headers=kh).status_code == 202
    assert client.post(EV, json=make_event(event_id="t-2"), headers=kh).status_code == 202  # stamped with the tenant
    assert count_events(customer_id="acme") == 2
    d = client.post(EVB, headers=kh, json={"events": [make_event(event_id="t-3", customer_id="acme"),
                                                      make_event(event_id="t-4", customer_id="globex")]}).json()
    assert (d["accepted"], d["rejected"]) == (1, 1) and d["results"][1]["code"] == "customer_mismatch"
    assert count_events(customer_id="globex") == 0
    free = client.post(K, headers=admin_headers, json={"name": "platform"}).json()["key"]  # un-scoped key: any customer
    assert client.post(EV, json=make_event(customer_id="globex"), headers={"X-API-Key": free}).status_code == 202
    assert client.get(EV, params={"customer_id": "acme"}, headers=admin_headers).json()["result"]["count"] == 3


def test_http_idempotency_key_replays_response(client, key_headers):
    body = make_event(event_id="idem-1")
    hdr = {**key_headers, "Idempotency-Key": "req-abc-123"}
    a = client.post(EV, json=body, headers=hdr)
    b = client.post(EV, json=body, headers=hdr)
    assert a.status_code == b.status_code == 202  # replayed (a plain retry would be 200 "duplicate")
    assert b.headers["idempotent-replayed"] == "true" and a.json() == b.json() and "idempotent-replayed" not in a.headers
    clash = client.post(EV, json=make_event(event_id="idem-2"), headers=hdr)
    assert clash.status_code == 409 and clash.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert client.post(EV, json=body, headers={**key_headers, "Idempotency-Key": "bad key"}).status_code == 422

    bb = {"events": [make_event(event_id="idem-b1"), make_event(event_id="idem-b2")]}
    h2 = {**key_headers, "Idempotency-Key": "batch-1"}
    r1, r2 = client.post(EVB, json=bb, headers=h2), client.post(EVB, json=bb, headers=h2)
    assert r1.json() == r2.json() and r2.json()["accepted"] == 2 and r2.headers["idempotent-replayed"] == "true"
    r3 = client.post(EVB, json=bb, headers=key_headers)  # without the header: event-level dedup instead
    assert r3.json()["duplicates"] == 2 and r3.json()["accepted"] == 0
