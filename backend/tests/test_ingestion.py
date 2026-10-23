import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.event import Event
from tests.helpers import make_event, running_app, wait_status

API = "/api/v1"


async def count_events(h, **where) -> int:
    async with h.session_factory() as s:
        stmt = select(func.count(Event.id))
        for k, v in where.items():
            stmt = stmt.where(getattr(Event, k) == v)
        return await s.scalar(stmt)


async def test_single_event_accepted_not_reported_as_processed(h, key_headers, admin_headers):
    body = make_event(event_id="order-1001")
    r = await h.client.post(f"{API}/events", json=body, headers=key_headers)
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "accepted" and data["event_id"] == "order-1001"
    assert data["processing_status"] in ("RECEIVED", "QUEUED")  # never PROCESSED at accept time
    done = await wait_status(h, admin_headers, data["id"], {"PROCESSED"})
    assert done["processing_duration_ms"] is not None and done["completed_at"] and done["retry_count"] == 0
    assert done["payload"]["order_id"] == body["payload"]["order_id"]


async def test_duplicate_event_is_detected_and_counted(h, key_headers, admin_headers):
    body = make_event(event_id="dup-1")
    first = await h.client.post(f"{API}/events", json=body, headers=key_headers)
    second = await h.client.post(f"{API}/events", json=body, headers=key_headers)
    third = await h.client.post(f"{API}/events", json=body, headers=key_headers)
    assert (first.status_code, second.status_code, third.status_code) == (202, 200, 200)
    assert second.json()["status"] == "duplicate" and second.json()["id"] == first.json()["id"]
    assert await count_events(h) == 1
    ev = (await h.client.get(f"{API}/events?event_id=dup-1", headers=admin_headers)).json()["items"][0]
    assert ev["duplicate_count"] == 2
    ov = (await h.client.get(f"{API}/analytics/overview", headers=admin_headers)).json()
    assert ov["duplicate_submissions"] == 2 and ov["total_received"] == 1


async def test_concurrent_duplicate_submissions_create_exactly_one_row(h, key_headers):
    body = make_event(event_id="race-1")
    rs = await asyncio.gather(*[h.client.post(f"{API}/events", json=body, headers=key_headers) for _ in range(25)])
    codes = sorted(r.status_code for r in rs)
    assert codes.count(202) == 1 and codes.count(200) == 24
    assert len({r.json()["id"] for r in rs}) == 1
    assert await count_events(h, event_id="race-1") == 1


async def test_concurrent_overlapping_batches(h, key_headers):
    ids = [f"ov-{i}" for i in range(10)]
    batch = {"events": [make_event(event_id=i) for i in ids]}
    rs = await asyncio.gather(*[h.client.post(f"{API}/events/batch", json=batch, headers=key_headers) for _ in range(6)])
    assert all(r.status_code == 202 for r in rs)
    assert sum(r.json()["accepted"] for r in rs) == 10  # each id accepted exactly once across all requests
    assert sum(r.json()["duplicates"] for r in rs) == 50
    assert await count_events(h) == 10


async def test_batch_reports_accepted_rejected_duplicates(h, key_headers):
    await h.client.post(f"{API}/events", json=make_event(event_id="pre-existing"), headers=key_headers)
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
    r = await h.client.post(f"{API}/events/batch", json=batch, headers=key_headers)
    assert r.status_code == 202
    data = r.json()
    assert (data["accepted"], data["duplicates"], data["rejected"]) == (2, 2, 4)
    by_index = {x["index"]: x for x in data["results"]}
    assert [by_index[i]["status"] for i in range(8)] == [
        "accepted", "rejected", "duplicate", "duplicate", "rejected", "rejected", "rejected", "accepted"]
    assert by_index[1]["code"] == "invalid_payload" and by_index[6]["code"] == "unsupported_schema_version"
    assert by_index[3]["code"] == "duplicate_in_batch" and by_index[0]["id"]
    assert await count_events(h) == 3  # pre-existing, b-1, b-4


async def test_batch_limits_and_shape(h, key_headers):
    r = await h.client.post(f"{API}/events/batch", json={"events": []}, headers=key_headers)
    assert r.status_code == 422
    assert (await h.client.post(f"{API}/events/batch", json={"nope": 1}, headers=key_headers)).status_code == 422


async def test_batch_too_large_is_413():
    async with running_app(max_batch_size=3) as h:
        from tests.helpers import make_user, auth_headers
        await make_user(h, "admin", ["ADMIN"])
        ah = await auth_headers(h, "admin")
        k = (await h.client.post(f"{API}/api-keys", json={"name": "k"}, headers=ah)).json()["key"]
        r = await h.client.post(f"{API}/events/batch", json={"events": [make_event() for _ in range(4)]}, headers={"X-API-Key": k})
        assert r.status_code == 413 and r.json()["error"]["code"] == "BATCH_TOO_LARGE"
        ok = await h.client.post(f"{API}/events/batch", json={"events": [make_event() for _ in range(3)]}, headers={"X-API-Key": k})
        assert ok.status_code == 202 and ok.json()["accepted"] == 3


async def test_request_body_size_limit_413():
    async with running_app(max_request_body_bytes=2000) as h:
        from tests.helpers import make_user, auth_headers
        await make_user(h, "admin", ["ADMIN"])
        ah = await auth_headers(h, "admin")
        k = (await h.client.post(f"{API}/api-keys", json={"name": "k"}, headers=ah)).json()["key"]
        big = make_event(payload={"blob": "x" * 5000, "order_id": "1", "amount": 1, "currency": "USD"})
        r = await h.client.post(f"{API}/events", json=big, headers={"X-API-Key": k})
        assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

        async def chunked():  # no Content-Length: enforced on streamed bytes
            for _ in range(10):
                yield b'{"x":"' + b"a" * 500 + b'"}'

        r2 = await h.client.post(f"{API}/events", content=chunked(), headers={"X-API-Key": k, "content-type": "application/json"})
        assert r2.status_code == 413


async def test_event_payload_too_large_413(h, key_headers):
    big = make_event(event_type="custom.big", payload={"blob": "x" * (h.settings.max_payload_bytes + 10)})
    r = await h.client.post(f"{API}/events", json=big, headers=key_headers)
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert await count_events(h) == 0


async def test_invalid_events_never_reach_the_worker(h, key_headers):
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
        r = await h.client.post(f"{API}/events", json=body, headers=key_headers)
        assert r.status_code == 422, (name, r.text)
    assert await count_events(h) == 0


async def test_timestamp_rules(h, key_headers):
    future = make_event(timestamp=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    r = await h.client.post(f"{API}/events", json=future, headers=key_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TIMESTAMP"
    old = make_event(timestamp=(datetime.now(timezone.utc) - timedelta(days=800)).isoformat())
    assert (await h.client.post(f"{API}/events", json=old, headers=key_headers)).status_code == 422
    ok = make_event(timestamp=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat())  # small clock skew ok
    assert (await h.client.post(f"{API}/events", json=ok, headers=key_headers)).status_code == 202
    tz = make_event(timestamp="2026-10-01T12:00:00+05:00")
    assert (await h.client.post(f"{API}/events", json=tz, headers=key_headers)).status_code == 202


async def test_unsupported_schema_version(h, key_headers):
    r = await h.client.post(f"{API}/events", json=make_event(schema_version="2.0"), headers=key_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNSUPPORTED_SCHEMA_VERSION"
    assert "1.0" in r.json()["error"]["message"]


async def test_event_specific_payload_requirements(h, key_headers):
    bad = [
        make_event(event_type="order.created", payload={"order_id": "1", "amount": -5, "currency": "USD"}),
        make_event(event_type="order.created", payload={"order_id": "1", "amount": "ten", "currency": "USD"}),
        make_event(event_type="payment.succeeded", payload={"payment_id": "p", "amount": 5, "currency": "DOLLARS"}),
        make_event(event_type="user.activity", payload={"user_id": "u"}),
        make_event(event_type="app.error", payload={"service": "api"}),
        make_event(event_type="service.health", payload={"service": "db", "status": "sleepy"}),
    ]
    for body in bad:
        r = await h.client.post(f"{API}/events", json=body, headers=key_headers)
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PAYLOAD", (body, r.text)
    good = [
        make_event(event_type="user.activity", payload={"user_id": "u", "action": "login"}),
        make_event(event_type="app.error", payload={"service": "api", "message": "boom"}),
        make_event(event_type="service.health", payload={"service": "db", "status": "degraded"}),
        make_event(event_type="payment.failed", payload={"payment_id": "p", "amount": 0, "currency": "eur"}),
    ]
    for body in good:
        assert (await h.client.post(f"{API}/events", json=body, headers=key_headers)).status_code == 202


async def test_nul_character_and_deep_nesting_rejected(h, key_headers):
    nul = make_event(event_type="custom.x", payload={"text": "a\u0000b"})
    assert (await h.client.post(f"{API}/events", json=nul, headers=key_headers)).status_code == 422
    deep: dict = {}
    cur = deep
    for _ in range(15):
        cur["n"] = {}
        cur = cur["n"]
    r = await h.client.post(f"{API}/events", json=make_event(event_type="custom.x", payload=deep), headers=key_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PAYLOAD"


async def test_tenant_isolation(h, admin_headers):
    key = (await h.client.post(f"{API}/api-keys", headers=admin_headers, json={"name": "acme", "customer_id": "acme"})).json()["key"]
    kh = {"X-API-Key": key}
    r = await h.client.post(f"{API}/events", json=make_event(customer_id="globex"), headers=kh)
    assert r.status_code == 403 and r.json()["error"]["code"] == "CUSTOMER_MISMATCH"
    assert await count_events(h) == 0

    ok = await h.client.post(f"{API}/events", json=make_event(event_id="t-1", customer_id="acme"), headers=kh)
    implicit = await h.client.post(f"{API}/events", json=make_event(event_id="t-2"), headers=kh)  # no customer_id -> stamped
    assert ok.status_code == implicit.status_code == 202
    assert await count_events(h, customer_id="acme") == 2

    batch = await h.client.post(f"{API}/events/batch", headers=kh, json={"events": [
        make_event(event_id="t-3", customer_id="acme"), make_event(event_id="t-4", customer_id="globex")]})
    d = batch.json()
    assert (d["accepted"], d["rejected"]) == (1, 1) and d["results"][1]["code"] == "customer_mismatch"
    assert await count_events(h, customer_id="globex") == 0

    # an un-scoped key may write for any customer
    free = (await h.client.post(f"{API}/api-keys", headers=admin_headers, json={"name": "platform"})).json()["key"]
    assert (await h.client.post(f"{API}/events", json=make_event(customer_id="globex"), headers={"X-API-Key": free})).status_code == 202
    listed = await h.client.get(f"{API}/events?customer_id=acme", headers=admin_headers)
    assert listed.json()["total"] == 3


async def test_http_idempotency_key_replays_response(h, key_headers):
    body = make_event(event_id="idem-1")
    hdr = {**key_headers, "Idempotency-Key": "req-abc-123"}
    a = await h.client.post(f"{API}/events", json=body, headers=hdr)
    b = await h.client.post(f"{API}/events", json=body, headers=hdr)
    assert a.status_code == b.status_code == 202  # replayed (a plain retry would have been 200 "duplicate")
    assert b.headers["idempotent-replayed"] == "true" and a.json() == b.json()
    assert "idempotent-replayed" not in a.headers
    clash = await h.client.post(f"{API}/events", json=make_event(event_id="idem-2"), headers=hdr)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert (await h.client.post(f"{API}/events", json=body, headers={**key_headers, "Idempotency-Key": "bad key"})).status_code in (422, 400)

    bb = {"events": [make_event(event_id="idem-b1"), make_event(event_id="idem-b2")]}
    h2 = {**key_headers, "Idempotency-Key": "batch-1"}
    r1 = await h.client.post(f"{API}/events/batch", json=bb, headers=h2)
    r2 = await h.client.post(f"{API}/events/batch", json=bb, headers=h2)
    assert r1.json() == r2.json() and r2.json()["accepted"] == 2 and r2.headers["idempotent-replayed"] == "true"
    # a retry WITHOUT the header is handled by event-level dedup instead
    r3 = await h.client.post(f"{API}/events/batch", json=bb, headers=key_headers)
    assert r3.json()["duplicates"] == 2 and r3.json()["accepted"] == 0
