from datetime import datetime, timedelta, timezone

import pytest

from app.models.event import DeadLetterEvent, Event

API = "/api/v1/analytics"


def hour_floor(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


@pytest.fixture
async def seeded(h, admin_headers):
    """Deterministic dataset (workers stopped so nothing changes underneath the assertions).

    group A = (current hour - 1h) + 10min ; group B = (current hour - 2h) + 10min
    """
    await h.manager.stop()
    now = datetime.now(timezone.utc)
    A = hour_floor(now) - timedelta(hours=1) + timedelta(minutes=10)
    B = hour_floor(now) - timedelta(hours=2) + timedelta(minutes=10)
    counter = iter(range(1000))

    def ev(etype, source, status, at, **kw):
        return Event(event_id=f"seed-{next(counter)}", event_type=etype, source=source, schema_version="1.0",
                     occurred_at=at, received_at=at, payload={}, status=status, **kw)

    events = [ev("order.created", "shop", "PROCESSED", A, customer_id="acme", processing_duration_ms=d)
              for d in (10, 20, 30, 40, 50, 100)]
    events += [ev("user.activity", "web", "PROCESSED", B, customer_id="globex", processing_duration_ms=d) for d in (5, 15)]
    dead = [ev("payment.failed", "billing", "DEAD_LETTER", A, retry_count=3, duplicate_count=2 if i == 0 else 0) for i in range(3)]
    events += dead
    events += [ev("order.created", "shop", "RETRYING", B, retry_count=1, next_retry_at=B),
               ev("custom.pending", "web", "RECEIVED", B),
               ev("custom.proc", "billing", "PROCESSING", A),
               ev("order.created", "shop", "PROCESSED", now - timedelta(days=3), processing_duration_ms=999)]  # outside 24h
    async with h.session_factory() as s:
        s.add_all(events)
        await s.flush()
        for i, d in enumerate(dead):
            s.add(DeadLetterEvent(event_id=d.id, failure_reason=f"boom {i}", retry_count=3,
                                  dead_lettered_at=A + timedelta(minutes=i),
                                  resolution_status="RESOLVED" if i == 2 else "OPEN"))
        await s.commit()
    return {"A": A, "B": B, "now": now, "hour": hour_floor(now)}


async def get(h, path, headers, **params):
    r = await h.client.get(f"{API}{path}", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_overview_metrics(h, admin_headers, seeded):
    o = await get(h, "/overview", admin_headers)
    assert (o["total_received"], o["processed"], o["failed"], o["pending"], o["processing"]) == (14, 8, 3, 2, 1)
    assert o["duplicate_submissions"] == 2 and o["retries_total"] == 10 and o["dead_letters_open"] == 2
    assert o["success_rate"] == pytest.approx(8 / 11, abs=1e-4) and o["failure_rate"] == pytest.approx(3 / 11, abs=1e-4)
    assert o["avg_processing_latency_ms"] == pytest.approx(33.75)
    assert o["events_per_minute"] == pytest.approx(14 / 1440, abs=1e-4)
    assert abs(o["window"]["minutes"] - 1440) < 1


async def test_overview_filters(h, admin_headers, seeded):
    assert (await get(h, "/overview", admin_headers, event_type="order.created"))["total_received"] == 7
    assert (await get(h, "/overview", admin_headers, source="web"))["total_received"] == 3
    assert (await get(h, "/overview", admin_headers, customer_id="globex"))["total_received"] == 2
    assert (await get(h, "/overview", admin_headers, status=["PROCESSED", "DEAD_LETTER"]))["total_received"] == 11
    wide = await get(h, "/overview", admin_headers, **{"from": (seeded["now"] - timedelta(days=5)).isoformat()})
    assert wide["total_received"] == 15 and wide["processed"] == 9


async def test_empty_dataset_has_no_division_by_zero(h, admin_headers):
    o = await get(h, "/overview", admin_headers)
    assert o["total_received"] == 0 and o["success_rate"] is None and o["failure_rate"] is None
    assert o["avg_processing_latency_ms"] is None and o["events_per_minute"] == 0.0
    lat = await get(h, "/processing-latency", admin_headers)
    assert lat["overall"]["samples"] == 0 and lat["overall"]["p95_ms"] is None
    assert (await get(h, "/events-by-type", admin_headers))["items"] == []
    assert (await get(h, "/failure-rates", admin_headers))["items"] == []
    assert (await get(h, "/top-sources", admin_headers))["items"] == []
    dl = await get(h, "/dead-letters", admin_headers)
    assert dl["total"] == 0 and dl["items"] == []
    ot = await get(h, "/events-over-time", admin_headers, interval="hour")
    assert all(b["count"] == 0 for b in ot["buckets"]) and len(ot["buckets"]) in (24, 25)


async def test_events_by_type_and_top_sources(h, admin_headers, seeded):
    by_type = {i["key"]: i["count"] for i in (await get(h, "/events-by-type", admin_headers))["items"]}
    assert by_type == {"order.created": 7, "payment.failed": 3, "user.activity": 2, "custom.pending": 1, "custom.proc": 1}
    top = (await get(h, "/top-sources", admin_headers, limit=2))["items"]
    assert top == [{"key": "shop", "count": 7}, {"key": "billing", "count": 4}]
    assert len((await get(h, "/events-by-type", admin_headers, limit=1))["items"]) == 1


async def test_events_over_time_gap_filled(h, admin_headers, seeded):
    hr = seeded["hour"]
    data = await get(h, "/events-over-time", admin_headers, interval="hour",
                     **{"from": (hr - timedelta(hours=3)).isoformat(), "to": hr.isoformat()})
    b = data["buckets"]
    assert [x["count"] for x in b] == [0, 4, 10] and [x["processed"] for x in b] == [0, 2, 6] and [x["failed"] for x in b] == [0, 0, 3]
    assert datetime.fromisoformat(b[1]["bucket"]) == hr - timedelta(hours=2)
    day = await get(h, "/events-over-time", admin_headers, interval="day", event_type="order.created",
                    **{"from": (seeded["now"] - timedelta(days=4)).isoformat()})
    assert sum(x["count"] for x in day["buckets"]) == 8


async def test_range_validation(h, admin_headers):
    now = datetime.now(timezone.utc)
    r = await h.client.get(f"{API}/overview", headers=admin_headers, params={"from": now.isoformat(), "to": (now - timedelta(hours=1)).isoformat()})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_RANGE"
    r = await h.client.get(f"{API}/events-over-time", headers=admin_headers, params={"interval": "minute", "from": (now - timedelta(days=30)).isoformat()})
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOO_MANY_BUCKETS"
    assert (await h.client.get(f"{API}/events-over-time", headers=admin_headers, params={"interval": "week"})).status_code == 422
    assert (await h.client.get(f"{API}/overview", headers=admin_headers, params={"status": "NOPE"})).status_code == 422


async def test_failure_rates(h, admin_headers, seeded):
    items = {i["key"]: i for i in (await get(h, "/failure-rates", admin_headers))["items"]}
    assert items["payment.failed"] == {"key": "payment.failed", "total": 3, "processed": 0, "failed": 3, "failure_rate": 1.0}
    assert items["order.created"]["failure_rate"] == 0.0 and items["order.created"]["total"] == 7
    assert items["custom.pending"]["failure_rate"] is None  # nothing finished -> undefined, not 0/0
    first = (await get(h, "/failure-rates", admin_headers))["items"][0]
    assert first["key"] == "payment.failed"  # worst first
    by_source = {i["key"]: i["failed"] for i in (await get(h, "/failure-rates", admin_headers, group_by="source"))["items"]}
    assert by_source["billing"] == 3


async def test_processing_latency_percentiles(h, admin_headers, seeded):
    lat = await get(h, "/processing-latency", admin_headers, event_type="order.created")
    o = lat["overall"]
    assert o["samples"] == 6 and o["min_ms"] == 10 and o["max_ms"] == 100
    assert o["avg_ms"] == pytest.approx(41.667, abs=1e-3) and o["p50_ms"] == 35 and o["p95_ms"] == 87.5 and o["p99_ms"] == 97.5
    grouped = await get(h, "/processing-latency", admin_headers, group_by="event_type")
    assert {g["key"]: g["samples"] for g in grouped["groups"]} == {"order.created": 6, "user.activity": 2}
    assert grouped["overall"]["samples"] == 8  # the 3-day-old event is outside the window


async def test_queue_status(h, admin_headers, seeded):
    q = await get(h, "/queue-status", admin_headers)
    assert q["queue_capacity"] == h.settings.event_queue_maxsize and q["queue_size"] == 0 and q["saturated"] is False
    assert q["db_counts"]["PROCESSED"] == 9 and q["db_counts"]["DEAD_LETTER"] == 3 and q["db_counts"]["RETRYING"] == 1
    assert q["db_counts"]["FAILED"] == 0  # every status is present, even when zero


async def test_dead_letters_filters_and_pagination(h, admin_headers, seeded):
    page1 = await get(h, "/dead-letters", admin_headers, limit=2, offset=0)
    page2 = await get(h, "/dead-letters", admin_headers, limit=2, offset=2)
    assert page1["total"] == 3 and len(page1["items"]) == 2 and len(page2["items"]) == 1
    reasons = [i["failure_reason"] for i in page1["items"] + page2["items"]]
    assert reasons == ["boom 2", "boom 1", "boom 0"]  # newest first, stable across pages
    assert (await get(h, "/dead-letters", admin_headers, resolution_status="OPEN"))["total"] == 2
    assert (await get(h, "/dead-letters", admin_headers, resolution_status="RESOLVED"))["items"][0]["failure_reason"] == "boom 2"
    assert (await get(h, "/dead-letters", admin_headers, source="shop"))["total"] == 0
    assert (await get(h, "/dead-letters", admin_headers, event_type="payment.failed"))["total"] == 3
    r = await h.client.get(f"{API}/dead-letters", headers=admin_headers, params={"limit": 0})
    assert r.status_code == 422


async def test_event_list_pagination_and_filters(h, admin_headers, seeded):
    ev = "/api/v1/events"
    first = (await h.client.get(ev, headers=admin_headers, params={"limit": 5, "offset": 0})).json()
    assert first["total"] == 15 and len(first["items"]) == 5 and first["limit"] == 5
    ids = []
    for off in (0, 5, 10):
        ids += [e["id"] for e in (await h.client.get(ev, headers=admin_headers, params={"limit": 5, "offset": off})).json()["items"]]
    assert len(set(ids)) == 15  # no duplicates / gaps across pages
    dead = (await h.client.get(ev, headers=admin_headers, params={"status": "DEAD_LETTER"})).json()
    assert dead["total"] == 3
    multi = (await h.client.get(ev, headers=admin_headers, params={"status": ["DEAD_LETTER", "RETRYING"]})).json()
    assert multi["total"] == 4
    ranged = (await h.client.get(ev, headers=admin_headers, params={"from": (seeded["now"] - timedelta(days=1)).isoformat()})).json()
    assert ranged["total"] == 14
    assert (await h.client.get(ev, headers=admin_headers, params={"limit": 1000})).status_code == 422
    assert (await h.client.get(ev, headers=admin_headers, params={"status": "WRONG"})).status_code == 422


async def test_analytics_requires_permission(h, seeded):
    from tests.helpers import auth_headers, make_user
    await make_user(h, "nobody", [])
    nh = await auth_headers(h, "nobody")
    for p in ("/overview", "/events-by-type", "/events-over-time", "/failure-rates", "/processing-latency",
              "/top-sources", "/queue-status", "/dead-letters"):
        assert (await h.client.get(f"{API}{p}", headers=nh)).status_code == 403, p
