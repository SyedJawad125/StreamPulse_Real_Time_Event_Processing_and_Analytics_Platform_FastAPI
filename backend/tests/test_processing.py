import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.event import AttemptOutcome, DeadLetterEvent, Event, EventStatus, ProcessingAttempt
from app.services import processing_service as ps
from tests.helpers import (
    auth_headers, fresh_session, get_event, ingest, make_event, make_user, running_app, wait_status, wait_until,
)

API = "/api/v1"


def flaky(fail_times: int, counter: Counter):
    async def handler(ctx: ps.EventContext) -> None:
        counter[ctx.event_id] += 1
        if counter[ctx.event_id] <= fail_times:
            raise ps.ProcessingError(f"transient failure #{counter[ctx.event_id]}")
    return handler


async def test_successful_processing_records_attempt(h, key_headers, admin_headers):
    created = await ingest(h, key_headers)
    ev = await wait_status(h, admin_headers, created["id"], {"PROCESSED"})
    assert [(a["attempt_number"], a["outcome"]) for a in ev["attempts"]] == [(1, "SUCCESS")]
    assert ev["attempts"][0]["duration_ms"] is not None and ev["last_error"] is None


async def test_retry_then_success(h, key_headers, admin_headers):
    calls = Counter()
    h.app.state.handlers.register("test.flaky", flaky(2, calls))
    created = await ingest(h, key_headers, event_type="test.flaky", payload={"a": 1})
    ev = await wait_status(h, admin_headers, created["id"], {"PROCESSED"})
    assert ev["retry_count"] == 2 and calls[created["event_id"]] == 3
    assert [a["outcome"] for a in ev["attempts"]] == ["FAILED", "FAILED", "SUCCESS"]
    assert ev["attempts"][0]["error"].startswith("ProcessingError: transient failure #1")
    assert ev["dead_letters"] == []


async def test_retries_exhausted_goes_to_dead_letter_with_sanitized_error(h, key_headers, admin_headers):
    async def always_fail(ctx):
        raise RuntimeError("db down: postgresql+asyncpg://u:hunter2@h/db token=abc123 Bearer eyJxyz.abc")

    h.app.state.handlers.register("test.fail", always_fail)
    created = await ingest(h, key_headers, event_type="test.fail", payload={})
    ev = await wait_status(h, admin_headers, created["id"], {"DEAD_LETTER"})
    assert ev["retry_count"] == h.settings.event_max_retries
    assert len(ev["attempts"]) == h.settings.event_max_retries + 1 and {a["outcome"] for a in ev["attempts"]} == {"FAILED"}
    blob = str(ev)
    for secret in ("hunter2", "abc123", "eyJxyz"):
        assert secret not in blob
    assert ev["completed_at"] and len(ev["dead_letters"]) == 1 and ev["dead_letters"][0]["resolution_status"] == "OPEN"

    dl = (await h.client.get(f"{API}/analytics/dead-letters", headers=admin_headers)).json()
    assert dl["total"] == 1 and dl["items"][0]["event_id"] == created["event_id"] and dl["items"][0]["retry_count"] == 2


async def test_non_retryable_error_skips_retries(h, key_headers, admin_headers):
    async def permanent(ctx):
        raise ps.NonRetryableProcessingError("unsupported currency")

    h.app.state.handlers.register("test.permanent", permanent)
    created = await ingest(h, key_headers, event_type="test.permanent", payload={})
    ev = await wait_status(h, admin_headers, created["id"], {"DEAD_LETTER"})
    assert len(ev["attempts"]) == 1 and ev["retry_count"] == 0 and "unsupported currency" in ev["last_error"]


async def test_handler_timeout_is_a_retryable_failure():
    async with running_app(event_processing_timeout_seconds=0.1, event_max_retries=1) as h:
        await make_user(h, "admin", ["ADMIN"]); ah = await auth_headers(h, "admin")
        k = {"X-API-Key": (await h.client.post(f"{API}/api-keys", json={"name": "k"}, headers=ah)).json()["key"]}

        async def slow(ctx):
            await asyncio.sleep(5)

        h.app.state.handlers.register("test.slow", slow)
        c = await ingest(h, k, event_type="test.slow", payload={})
        ev = await wait_status(h, ah, c["id"], {"DEAD_LETTER"})
        assert "timed out" in ev["last_error"] and len(ev["attempts"]) == 2


async def test_manual_reprocess_flow_and_dead_letter_resolution(h, key_headers, admin_headers, operator_headers):
    mode = {"fail": True}

    async def handler(ctx):
        if mode["fail"]:
            raise ps.ProcessingError("still broken")

    h.app.state.handlers.register("test.repro", handler)
    c = await ingest(h, key_headers, event_type="test.repro", payload={})
    await wait_status(h, operator_headers, c["id"], {"DEAD_LETTER"})

    mode["fail"] = False
    r = await h.client.post(f"{API}/events/{c['id']}/reprocess", headers=operator_headers)
    assert r.status_code == 202 and r.json()["status"] in ("QUEUED", "RECEIVED")
    ev = await wait_status(h, operator_headers, c["id"], {"PROCESSED"})
    assert ev["retry_count"] == 0 and len(ev["attempts"]) == h.settings.event_max_retries + 2  # history preserved
    assert [a["attempt_number"] for a in ev["attempts"]] == list(range(1, len(ev["attempts"]) + 1))
    assert ev["dead_letters"][0]["resolution_status"] == "REPROCESSED" and ev["dead_letters"][0]["resolved_by_user_id"]

    logs = (await h.client.get(f"{API}/admin/audit-logs?action=event.reprocessed", headers=admin_headers)).json()
    assert logs["total"] == 1 and logs["items"][0]["target_id"] == c["id"]

    # PROCESSED events are not eligible
    again = await h.client.post(f"{API}/events/{c['id']}/reprocess", headers=operator_headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "NOT_REPROCESSABLE"


async def test_reprocess_authorization(h, key_headers, viewer_headers, analyst_headers, operator_headers):
    async def fail(ctx):
        raise ps.NonRetryableProcessingError("nope")

    h.app.state.handlers.register("test.auth", fail)
    c = await ingest(h, key_headers, event_type="test.auth", payload={})
    await wait_status(h, operator_headers, c["id"], {"DEAD_LETTER"})
    url = f"{API}/events/{c['id']}/reprocess"
    assert (await h.client.post(url)).status_code == 401
    assert (await h.client.post(url, headers={"X-API-Key": key_headers["X-API-Key"]})).status_code == 401
    assert (await h.client.post(url, headers=viewer_headers)).status_code == 403
    assert (await h.client.post(url, headers=analyst_headers)).status_code == 403
    assert (await get_event(h, operator_headers, c["id"]))["status"] == "DEAD_LETTER"  # untouched by denied calls
    assert (await h.client.post(url, headers=operator_headers)).status_code == 202
    assert (await h.client.post(f"{API}/events/00000000-0000-0000-0000-000000000000/reprocess", headers=operator_headers)).status_code == 404


async def test_resolve_dead_letter(h, key_headers, operator_headers, viewer_headers):
    async def fail(ctx):
        raise ps.NonRetryableProcessingError("bad data")

    h.app.state.handlers.register("test.res", fail)
    c = await ingest(h, key_headers, event_type="test.res", payload={})
    ev = await wait_status(h, operator_headers, c["id"], {"DEAD_LETTER"})
    dl_id = ev["dead_letters"][0]["id"]
    url = f"{API}/events/dead-letters/{dl_id}/resolve"
    assert (await h.client.post(url, json={}, headers=viewer_headers)).status_code == 403
    r = await h.client.post(url, json={"details": "discarded: test data"}, headers=operator_headers)
    assert r.status_code == 200 and r.json()["resolution_status"] == "RESOLVED" and r.json()["resolution_details"] == "discarded: test data"
    assert (await h.client.post(url, json={}, headers=operator_headers)).status_code == 409
    assert (await h.client.get(f"{API}/analytics/dead-letters?resolution_status=OPEN", headers=operator_headers)).json()["total"] == 0


async def test_queue_full_returns_503_and_recovers():
    async with running_app(event_queue_maxsize=2, event_worker_concurrency=1) as h:
        await make_user(h, "admin", ["ADMIN"]); ah = await auth_headers(h, "admin")
        k = {"X-API-Key": (await h.client.post(f"{API}/api-keys", json={"name": "k"}, headers=ah)).json()["key"]}
        started, gate = asyncio.Event(), asyncio.Event()

        async def blocker(ctx):
            started.set()
            await gate.wait()

        h.app.state.handlers.register("test.block", blocker)
        first = await ingest(h, k, event_type="test.block", payload={})
        await asyncio.wait_for(started.wait(), 5)  # the single worker is now busy
        a = await h.client.post(f"{API}/events", json=make_event(event_type="test.block", payload={}), headers=k)
        b = await h.client.post(f"{API}/events", json=make_event(event_type="test.block", payload={}), headers=k)
        assert a.status_code == b.status_code == 202
        assert h.manager.status()["saturated"] is True and h.manager.queue.size == 2

        full = await h.client.post(f"{API}/events", json=make_event(event_type="test.block", payload={}), headers=k)
        assert full.status_code == 503 and full.json()["error"]["code"] == "QUEUE_FULL" and full.headers["retry-after"]
        batch = await h.client.post(f"{API}/events/batch", json={"events": [make_event()]}, headers=k)
        assert batch.status_code == 503
        q = (await h.client.get(f"{API}/analytics/queue-status", headers=ah)).json()
        assert q["saturated"] is True and q["queue_size"] == 2 and q["utilization"] == 1.0
        async with h.session_factory() as s:  # memory stays bounded; nothing was persisted for rejected requests
            assert len((await s.scalars(select(Event.id))).all()) == 3

        gate.set()
        await wait_status(h, ah, first["id"], {"PROCESSED"})
        await wait_until(lambda: _all_processed(h, 3))
        ok = await h.client.post(f"{API}/events", json=make_event(), headers=k)
        assert ok.status_code == 202


async def _all_processed(h, n) -> bool:
    async with h.session_factory() as s:
        rows = (await s.scalars(select(Event.status))).all()
    return len(rows) == n and all(r == "PROCESSED" for r in rows)


async def test_restart_recovery_redispatches_everything_pending():
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    async with running_app() as a:
        await make_user(a, "admin", ["ADMIN"])
        await a.manager.stop()  # simulate: workers gone, DB left in assorted mid-flight states
        async with a.session_factory() as s:
            def mk(eid, status, **kw):
                return Event(event_id=eid, event_type="custom.recover", source="s", schema_version="1.0",
                             occurred_at=past, payload={}, status=status, **kw)
            interrupted = mk("r-processing", "PROCESSING", retry_count=0, processing_started_at=past)
            s.add_all([mk("r-received", "RECEIVED"), mk("r-queued", "QUEUED"),
                       mk("r-retrying", "RETRYING", retry_count=1, next_retry_at=past), interrupted,
                       mk("r-exhausted", "PROCESSING", retry_count=2, processing_started_at=past)])
            await s.flush()
            for ev in (interrupted,):
                s.add(ProcessingAttempt(event_id=ev.id, attempt_number=1, started_at=past, outcome="RUNNING"))
            await s.commit()

    async with running_app() as b:  # "restart": startup recovery runs in the lifespan
        ah = await auth_headers(b, "admin")
        listing = (await b.client.get(f"{API}/events?limit=50", headers=ah)).json()["items"]
        by_id = {e["event_id"]: e for e in listing}
        await wait_until(lambda: _statuses_settled(b), timeout=10)
        listing = (await b.client.get(f"{API}/events?limit=50", headers=ah)).json()["items"]
        by_id = {e["event_id"]: e for e in listing}
        assert {k: v["status"] for k, v in by_id.items()} == {
            "r-received": "PROCESSED", "r-queued": "PROCESSED", "r-retrying": "PROCESSED",
            "r-processing": "PROCESSED", "r-exhausted": "DEAD_LETTER"}
        detail = await get_event(b, ah, by_id["r-processing"]["id"])
        assert [x["outcome"] for x in detail["attempts"]] == ["INTERRUPTED", "SUCCESS"] and detail["retry_count"] == 1


async def _statuses_settled(h) -> bool:
    async with h.session_factory() as s:
        rows = (await s.scalars(select(Event.status))).all()
    return len(rows) == 5 and all(r in ("PROCESSED", "DEAD_LETTER") for r in rows)


async def test_graceful_shutdown_mid_processing_marks_interrupted_and_resumes():
    started = asyncio.Event()
    async with running_app(event_shutdown_grace_seconds=0.3) as a:
        await make_user(a, "admin", ["ADMIN"]); ah = await auth_headers(a, "admin")
        k = {"X-API-Key": (await a.client.post(f"{API}/api-keys", json={"name": "k"}, headers=ah)).json()["key"]}

        async def hang(ctx):
            started.set()
            await asyncio.Event().wait()

        a.app.state.handlers.register("test.hang", hang)
        c = await ingest(a, k, event_type="test.hang", payload={})
        await asyncio.wait_for(started.wait(), 5)
    # lifespan exited: in-flight work was cancelled after the grace period and recorded as interrupted
    async with fresh_session() as s:
        ev = await s.scalar(select(Event).where(Event.event_id == c["event_id"]))
        attempts = (await s.scalars(select(ProcessingAttempt.outcome).where(ProcessingAttempt.event_id == ev.id))).all()
    assert ev.status == "RETRYING" and list(attempts) == ["INTERRUPTED"] and ev.retry_count == 1
    async with running_app() as b:  # next start finishes the job (default handler)
        ah = await auth_headers(b, "admin")
        done = await wait_status(b, ah, c["id"], {"PROCESSED"})
        assert [x["outcome"] for x in done["attempts"]] == ["INTERRUPTED", "SUCCESS"]


async def test_each_event_processed_exactly_once_under_concurrency():
    async with running_app(event_worker_concurrency=4) as h:
        await make_user(h, "admin", ["ADMIN"]); ah = await auth_headers(h, "admin")
        k = {"X-API-Key": (await h.client.post(f"{API}/api-keys", json={"name": "k"}, headers=ah)).json()["key"]}
        calls: Counter = Counter()

        async def count(ctx):
            calls[ctx.event_id] += 1
            await asyncio.sleep(0.01)

        h.app.state.handlers.register("test.count", count)
        ids = [f"cc-{i}" for i in range(60)]
        await asyncio.gather(*[h.client.post(f"{API}/events", json=make_event(event_id=i, event_type="test.count", payload={}), headers=k) for i in ids])
        await wait_until(lambda: _all_processed(h, 60), timeout=15)
        assert set(calls) == set(ids) and all(v == 1 for v in calls.values())
        async with h.session_factory() as s:
            n_attempts = len((await s.scalars(select(ProcessingAttempt.id))).all())
        assert n_attempts == 60


async def test_claim_is_atomic_across_competing_workers(h):
    await h.manager.stop()
    past = datetime.now(timezone.utc)
    async with h.session_factory() as s:
        ev = Event(event_id="claim-1", event_type="x.y", source="s", schema_version="1.0", occurred_at=past, payload={}, status="QUEUED")
        s.add(ev); await s.commit()
        pk = ev.id

    async def claim():
        async with h.session_factory() as s:
            return await ps.claim_event(s, pk)

    results = await asyncio.gather(*[claim() for _ in range(8)])
    assert sum(r is not None for r in results) == 1
    async with h.session_factory() as s:
        assert len((await s.scalars(select(ProcessingAttempt.id).where(ProcessingAttempt.event_id == pk))).all()) == 1


async def test_sweeper_dispatches_events_that_were_not_queued():
    """If the in-memory queue lost track of an event (e.g. it was saturated), PostgreSQL still drives it to completion."""
    async with running_app() as h:
        await make_user(h, "admin", ["ADMIN"]); ah = await auth_headers(h, "admin")
        async with h.session_factory() as s:
            ev = Event(event_id="orphan-1", event_type="x.y", source="s", schema_version="1.0",
                       occurred_at=datetime.now(timezone.utc), payload={}, status="RECEIVED")
            s.add(ev); await s.commit(); pk = str(ev.id)
        await wait_status(h, ah, pk, {"PROCESSED"})
