import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.crud import processing as ps
from app.database import SessionLocal
from app.main import app
from app.models import Event, ProcessingAttempt
from tests.helpers import (EV, K, R, U, get_event, ingest, login_headers, make_event, make_user, wait_status,
                           wait_until)


def flaky(fail_times: int, counter: Counter):
    def handler(ctx: ps.EventContext) -> None:
        counter[ctx.event_id] += 1
        if counter[ctx.event_id] <= fail_times:
            raise ps.ProcessingError(f"transient failure #{counter[ctx.event_id]}")
    return handler


def test_successful_processing_records_attempt(client, key_headers, admin_headers):
    created = ingest(client, key_headers)
    ev = wait_status(client, admin_headers, created["id"], {"PROCESSED"})
    assert [(a["attempt_number"], a["outcome"]) for a in ev["attempts"]] == [(1, "SUCCESS")]
    assert ev["attempts"][0]["duration_ms"] is not None and ev["last_error"] is None


def test_retry_then_success(client, key_headers, admin_headers):
    calls = Counter()
    client.app.state.handlers.register("test.flaky", flaky(2, calls))
    created = ingest(client, key_headers, event_type="test.flaky", payload={"a": 1})
    ev = wait_status(client, admin_headers, created["id"], {"PROCESSED"})
    assert ev["retry_count"] == 2 and calls[created["event_id"]] == 3
    assert [a["outcome"] for a in ev["attempts"]] == ["FAILED", "FAILED", "SUCCESS"]
    assert ev["attempts"][0]["error"].startswith("ProcessingError: transient failure #1") and ev["dead_letters"] == []


def test_async_handlers_are_supported(client, key_headers, admin_headers):
    async def handler(ctx):
        assert ctx.payload["a"] == 1

    client.app.state.handlers.register("test.async", handler)
    created = ingest(client, key_headers, event_type="test.async", payload={"a": 1})
    assert wait_status(client, admin_headers, created["id"], {"PROCESSED"})["retry_count"] == 0


def test_retries_exhausted_goes_to_dead_letter_with_sanitized_error(client, key_headers, admin_headers):
    def always_fail(ctx):
        raise RuntimeError("db down: postgresql+psycopg2://u:hunter2@h/db token=abc123 Bearer eyJxyz.abc")

    client.app.state.handlers.register("test.fail", always_fail)
    created = ingest(client, key_headers, event_type="test.fail", payload={})
    ev = wait_status(client, admin_headers, created["id"], {"DEAD_LETTER"})
    assert ev["retry_count"] == settings.EVENT_MAX_RETRIES
    assert len(ev["attempts"]) == settings.EVENT_MAX_RETRIES + 1 and {a["outcome"] for a in ev["attempts"]} == {"FAILED"}
    for secret in ("hunter2", "abc123", "eyJxyz"):
        assert secret not in str(ev)
    assert ev["completed_at"] and len(ev["dead_letters"]) == 1 and ev["dead_letters"][0]["resolution_status"] == "OPEN"
    dl = client.get("/api/analytics/v1/dead-letters/", headers=admin_headers).json()["result"]
    assert dl["count"] == 1 and dl["data"][0]["event_id"] == created["event_id"] and dl["data"][0]["retry_count"] == 2


def test_non_retryable_error_skips_retries(client, key_headers, admin_headers):
    def permanent(ctx):
        raise ps.NonRetryableProcessingError("unsupported currency")

    client.app.state.handlers.register("test.permanent", permanent)
    created = ingest(client, key_headers, event_type="test.permanent", payload={})
    ev = wait_status(client, admin_headers, created["id"], {"DEAD_LETTER"})
    assert len(ev["attempts"]) == 1 and ev["retry_count"] == 0 and "unsupported currency" in ev["last_error"]


def test_handler_timeout_is_a_retryable_failure(client, key_headers, admin_headers, monkeypatch):
    monkeypatch.setattr(settings, "EVENT_PROCESSING_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(settings, "EVENT_MAX_RETRIES", 1)
    release = threading.Event()
    client.app.state.handlers.register("test.slow", lambda ctx: release.wait(5))
    created = ingest(client, key_headers, event_type="test.slow", payload={})
    ev = wait_status(client, admin_headers, created["id"], {"DEAD_LETTER"})
    release.set()
    assert "timed out" in ev["last_error"] and len(ev["attempts"]) == 2


def test_manual_reprocess_flow_and_audit(client, key_headers, admin_headers, operator_headers):
    mode = {"fail": True}

    def handler(ctx):
        if mode["fail"]:
            raise ps.ProcessingError("still broken")

    client.app.state.handlers.register("test.repro", handler)
    c = ingest(client, key_headers, event_type="test.repro", payload={})
    wait_status(client, operator_headers, c["id"], {"DEAD_LETTER"})
    mode["fail"] = False
    r = client.post(f"{EV}{c['id']}/reprocess", headers=operator_headers)
    assert r.status_code == 202 and r.json()["status"] in ("QUEUED", "RECEIVED")
    ev = wait_status(client, operator_headers, c["id"], {"PROCESSED"})
    assert ev["retry_count"] == 0 and len(ev["attempts"]) == settings.EVENT_MAX_RETRIES + 2  # history preserved
    assert [a["attempt_number"] for a in ev["attempts"]] == list(range(1, len(ev["attempts"]) + 1))
    assert ev["dead_letters"][0]["resolution_status"] == "REPROCESSED" and ev["dead_letters"][0]["resolved_by_user_id"]
    logs = client.get("/api/audit/v1/audit-log/", params={"action": "event.reprocessed"}, headers=admin_headers).json()["result"]
    assert logs["count"] == 1 and logs["data"][0]["target_id"] == str(c["id"])
    again = client.post(f"{EV}{c['id']}/reprocess", headers=operator_headers)
    assert again.status_code == 409 and again.json()["code"] == "NOT_REPROCESSABLE"


def test_reprocess_authorization(client, key_headers, viewer_headers, analyst_headers, operator_headers):
    def fail(ctx):
        raise ps.NonRetryableProcessingError("nope")

    client.app.state.handlers.register("test.auth", fail)
    c = ingest(client, key_headers, event_type="test.auth", payload={})
    wait_status(client, operator_headers, c["id"], {"DEAD_LETTER"})
    url = f"{EV}{c['id']}/reprocess"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=key_headers).status_code == 401
    assert client.post(url, headers=viewer_headers).status_code == 403
    assert client.post(url, headers=analyst_headers).status_code == 403
    assert get_event(client, operator_headers, c["id"])["status"] == "DEAD_LETTER"  # untouched by denied calls
    assert client.post(url, headers=operator_headers).status_code == 202
    assert client.post(f"{EV}999999/reprocess", headers=operator_headers).status_code == 404


def test_resolve_dead_letter(client, key_headers, operator_headers, viewer_headers):
    def fail(ctx):
        raise ps.NonRetryableProcessingError("bad data")

    client.app.state.handlers.register("test.res", fail)
    c = ingest(client, key_headers, event_type="test.res", payload={})
    ev = wait_status(client, operator_headers, c["id"], {"DEAD_LETTER"})
    url = f"/api/events/v1/dead-letter/{ev['dead_letters'][0]['id']}/resolve"
    assert client.post(url, json={}, headers=viewer_headers).status_code == 403
    r = client.post(url, json={"details": "discarded: test data"}, headers=operator_headers)
    assert r.status_code == 200 and r.json()["resolution_status"] == "RESOLVED" and r.json()["resolution_details"] == "discarded: test data"
    assert client.post(url, json={}, headers=operator_headers).status_code == 409
    assert client.get("/api/analytics/v1/dead-letters/", params={"resolution_status": "OPEN"}, headers=operator_headers).json()["result"]["count"] == 0


def test_queue_full_returns_503_and_recovers(monkeypatch):
    monkeypatch.setattr(settings, "EVENT_QUEUE_MAXSIZE", 2)
    monkeypatch.setattr(settings, "EVENT_WORKER_CONCURRENCY", 1)
    started, gate = threading.Event(), threading.Event()
    with TestClient(app) as c:
        make_user("admin@example.com", "su", superuser=True)
        ah = login_headers(c, "admin@example.com")
        k = {"X-API-Key": c.post(K, json={"name": "k"}, headers=ah).json()["key"]}

        def blocker(ctx):
            started.set()
            gate.wait(10)

        c.app.state.handlers.register("test.block", blocker)
        first = ingest(c, k, event_type="test.block", payload={})
        assert started.wait(5)  # the single worker is now busy
        a = c.post(EV, json=make_event(event_type="test.block", payload={}), headers=k)
        b = c.post(EV, json=make_event(event_type="test.block", payload={}), headers=k)
        assert a.status_code == b.status_code == 202
        m = c.app.state.worker_manager
        assert m.status()["saturated"] is True and m.queue.size == 2

        full = c.post(EV, json=make_event(event_type="test.block", payload={}), headers=k)
        assert full.status_code == 503 and full.json()["code"] == "QUEUE_FULL" and full.headers["retry-after"]
        assert c.post("/api/events/v1/event/batch/", json={"events": [make_event()]}, headers=k).status_code == 503
        q = c.get("/api/analytics/v1/queue-status/", headers=ah).json()
        assert q["saturated"] is True and q["queue_size"] == 2 and q["utilization"] == 1.0
        with SessionLocal() as db:  # memory stays bounded; rejected requests persisted nothing
            assert len(db.scalars(select(Event.id)).all()) == 3
        gate.set()
        wait_status(c, ah, first["id"], {"PROCESSED"})
        wait_until(lambda: _all_processed(3))
        assert c.post(EV, json=make_event(), headers=k).status_code == 202


def _all_processed(n: int) -> bool:
    with SessionLocal() as db:
        rows = db.scalars(select(Event.status)).all()
    return len(rows) == n and all(r == "PROCESSED" for r in rows)


def test_restart_recovery_redispatches_everything_pending():
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    with TestClient(app) as a:
        make_user("admin@example.com", "su", superuser=True)
        a.app.state.worker_manager.stop()  # simulate: workers gone, DB left in assorted mid-flight states
        with SessionLocal() as db:
            def mk(eid, status, **kw):
                return Event(event_id=eid, event_type="custom.recover", source="s", schema_version="1.0",
                             occurred_at=past, payload={}, status=status, **kw)
            interrupted = mk("r-processing", "PROCESSING", retry_count=0, processing_started_at=past)
            db.add_all([mk("r-received", "RECEIVED"), mk("r-queued", "QUEUED"),
                        mk("r-retrying", "RETRYING", retry_count=1, next_retry_at=past), interrupted,
                        mk("r-exhausted", "PROCESSING", retry_count=2, processing_started_at=past)])
            db.flush()
            db.add(ProcessingAttempt(event_id=interrupted.id, attempt_number=1, started_at=past, outcome="RUNNING"))
            db.commit()

    with TestClient(app) as b:  # "restart": startup recovery runs in the lifespan
        ah = login_headers(b, "admin@example.com")
        wait_until(lambda: _settled(5), timeout=10)
        items = b.get(EV, params={"limit": 50}, headers=ah).json()["result"]["data"]
        by_id = {e["event_id"]: e for e in items}
        assert {k: v["status"] for k, v in by_id.items()} == {
            "r-received": "PROCESSED", "r-queued": "PROCESSED", "r-retrying": "PROCESSED",
            "r-processing": "PROCESSED", "r-exhausted": "DEAD_LETTER"}
        detail = get_event(b, ah, by_id["r-processing"]["id"])
        assert [x["outcome"] for x in detail["attempts"]] == ["INTERRUPTED", "SUCCESS"] and detail["retry_count"] == 1


def _settled(n: int) -> bool:
    with SessionLocal() as db:
        rows = db.scalars(select(Event.status)).all()
    return len(rows) == n and all(r in ("PROCESSED", "DEAD_LETTER") for r in rows)


def test_graceful_shutdown_mid_processing_marks_interrupted_and_resumes(monkeypatch):
    monkeypatch.setattr(settings, "EVENT_SHUTDOWN_GRACE_SECONDS", 0.3)
    started, release = threading.Event(), threading.Event()
    with TestClient(app) as a:
        make_user("admin@example.com", "su", superuser=True)
        ah = login_headers(a, "admin@example.com")
        k = {"X-API-Key": a.post(K, json={"name": "k"}, headers=ah).json()["key"]}

        def hang(ctx):
            started.set()
            release.wait(10)

        a.app.state.handlers.register("test.hang", hang)
        c = ingest(a, k, event_type="test.hang", payload={})
        assert started.wait(5)
    # lifespan exited: the in-flight event was recorded as interrupted after the grace period
    with SessionLocal() as db:
        ev = db.scalar(select(Event).where(Event.event_id == c["event_id"]))
        attempts = db.scalars(select(ProcessingAttempt.outcome).where(ProcessingAttempt.event_id == ev.id)).all()
        assert ev.status == "RETRYING" and list(attempts) == ["INTERRUPTED"] and ev.retry_count == 1
    with TestClient(app) as b:  # next start finishes the job (default handler)
        release.set()  # the abandoned straggler thread may now return - it must NOT clobber the new attempt
        ah = login_headers(b, "admin@example.com")
        done = wait_status(b, ah, c["id"], {"PROCESSED"})
        assert [x["outcome"] for x in done["attempts"]] == ["INTERRUPTED", "SUCCESS"]


def test_each_event_processed_exactly_once_under_concurrency(monkeypatch):
    monkeypatch.setattr(settings, "EVENT_WORKER_CONCURRENCY", 4)
    with TestClient(app) as c:
        make_user("admin@example.com", "su", superuser=True)
        ah = login_headers(c, "admin@example.com")
        k = {"X-API-Key": c.post(K, json={"name": "k"}, headers=ah).json()["key"]}
        calls: Counter = Counter()
        lock = threading.Lock()

        def count(ctx):
            with lock:
                calls[ctx.event_id] += 1
            time.sleep(0.01)

        c.app.state.handlers.register("test.count", count)
        ids = [f"cc-{i}" for i in range(60)]
        with ThreadPoolExecutor(12) as pool:
            list(pool.map(lambda i: c.post(EV, json=make_event(event_id=i, event_type="test.count", payload={}), headers=k), ids))
        wait_until(lambda: _all_processed(60), timeout=15)
        assert set(calls) == set(ids) and all(v == 1 for v in calls.values())
        with SessionLocal() as db:
            assert len(db.scalars(select(ProcessingAttempt.id)).all()) == 60


def test_claim_is_atomic_across_competing_workers(client, manager):
    manager.stop()
    with SessionLocal() as db:
        ev = Event(event_id="claim-1", event_type="x.y", source="s", schema_version="1.0",
                   occurred_at=datetime.now(timezone.utc), payload={}, status="QUEUED")
        db.add(ev)
        db.commit()
        pk = ev.id

    def claim(_):
        with SessionLocal() as s:
            return ps.claim_event(s, pk)

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(claim, range(8)))
    assert sum(r is not None for r in results) == 1
    with SessionLocal() as db:
        assert len(db.scalars(select(ProcessingAttempt.id).where(ProcessingAttempt.event_id == pk)).all()) == 1


def test_stale_attempt_cannot_overwrite_newer_state(client, manager):
    """Fencing: a straggler whose attempt was interrupted/superseded can never complete or fail the event."""
    manager.stop()
    with SessionLocal() as db:
        ev = Event(event_id="fence-1", event_type="x.y", source="s", schema_version="1.0",
                   occurred_at=datetime.now(timezone.utc), payload={}, status="QUEUED")
        db.add(ev)
        db.commit()
        pk = ev.id
    with SessionLocal() as db:
        ctx1 = ps.claim_event(db, pk)                                   # attempt 1 starts ...
    with SessionLocal() as db:
        ps.register_failure(db, pk, "interrupted", retryable=True, duration_ms=None,
                            outcome=ps.AttemptOutcome.INTERRUPTED, attempt_number=1)   # ... is interrupted ...
    with SessionLocal() as db:
        db.execute(Event.__table__.update().where(Event.id == pk).values(status="QUEUED"))
        db.commit()
        ctx2 = ps.claim_event(db, pk)                                   # ... attempt 2 is now running
    assert ctx2.attempt_number == 2
    with SessionLocal() as db:
        assert ps.mark_success(db, pk, ctx1.attempt_number, 1.0) is False   # the straggler is ignored
    with SessionLocal() as db:
        assert ps.register_failure(db, pk, "late", retryable=False, duration_ms=1.0, attempt_number=1) is None
        assert db.get(Event, pk).status == "PROCESSING"
    with SessionLocal() as db:
        assert ps.mark_success(db, pk, 2, 1.0) is True


def test_sweeper_dispatches_events_that_were_not_queued(client, admin_headers):
    with SessionLocal() as db:
        ev = Event(event_id="orphan-1", event_type="x.y", source="s", schema_version="1.0",
                   occurred_at=datetime.now(timezone.utc), payload={}, status="RECEIVED")
        db.add(ev)
        db.commit()
        pk = ev.id
    wait_status(client, admin_headers, pk, {"PROCESSED"})
