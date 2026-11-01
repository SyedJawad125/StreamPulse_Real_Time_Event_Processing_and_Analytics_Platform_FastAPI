from datetime import datetime, timedelta, timezone

import pytest

from app.database import SessionLocal
from app.models import DeadLetterEvent, Event
from tests.helpers import AN, EV, login_headers, make_user


def hour_floor(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


@pytest.fixture
def seeded(client, manager, admin_headers):
    """Deterministic dataset (workers stopped so nothing changes underneath the assertions).

    group A = (current hour - 1h) + 10min ; group B = (current hour - 2h) + 10min
    """
    manager.stop()
    now = datetime.now(timezone.utc)
    A = hour_floor(now) - timedelta(hours=1) + timedelta(minutes=10)
    B = hour_floor(now) - timedelta(hours=2) + timedelta(minutes=10)
    n = iter(range(1000))

    def ev(etype, source, status, at, **kw):
        return Event(event_id=f"seed-{next(n)}", event_type=etype, source=source, schema_version="1.0",
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
    with SessionLocal() as db:
        db.add_all(events)
        db.flush()
        for i, d in enumerate(dead):
            db.add(DeadLetterEvent(event_id=d.id, failure_reason=f"boom {i}", retry_count=3,
                                   dead_lettered_at=A + timedelta(minutes=i),
                                   resolution_status="RESOLVED" if i == 2 else "OPEN"))
        db.commit()
    return {"A": A, "B": B, "now": now, "hour": hour_floor(now)}


def get(client, path, headers, **params):
    r = client.get(f"{AN}{path}", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_overview_metrics(client, admin_headers, seeded):
    o = get(client, "/overview/", admin_headers)
    assert (o["total_received"], o["processed"], o["failed"], o["pending"], o["processing"]) == (14, 8, 3, 2, 1)
    assert o["duplicate_submissions"] == 2 and o["retries_total"] == 10 and o["dead_letters_open"] == 2
    assert o["success_rate"] == pytest.approx(8 / 11, abs=1e-4) and o["failure_rate"] == pytest.approx(3 / 11, abs=1e-4)
    assert o["avg_processing_latency_ms"] == pytest.approx(33.75)
    assert o["events_per_minute"] == pytest.approx(14 / 1440, abs=1e-4) and abs(o["window"]["minutes"] - 1440) < 1


def test_overview_filters(client, admin_headers, seeded):
    assert get(client, "/overview/", admin_headers, event_type="order.created")["total_received"] == 7
    assert get(client, "/overview/", admin_headers, source="web")["total_received"] == 3
    assert get(client, "/overview/", admin_headers, customer_id="globex")["total_received"] == 2
    assert get(client, "/overview/", admin_headers, status=["PROCESSED", "DEAD_LETTER"])["total_received"] == 11
    wide = get(client, "/overview/", admin_headers, **{"from": (seeded["now"] - timedelta(days=5)).isoformat()})
    assert wide["total_received"] == 15 and wide["processed"] == 9


def test_empty_dataset_has_no_division_by_zero(client, admin_headers):
    o = get(client, "/overview/", admin_headers)
    assert o["total_received"] == 0 and o["success_rate"] is None and o["failure_rate"] is None
    assert o["avg_processing_latency_ms"] is None and o["events_per_minute"] == 0.0
    lat = get(client, "/processing-latency/", admin_headers)
    assert lat["overall"]["samples"] == 0 and lat["overall"]["p95_ms"] is None
    assert get(client, "/events-by-type/", admin_headers)["items"] == []
    assert get(client, "/failure-rates/", admin_headers)["items"] == []
    assert get(client, "/top-sources/", admin_headers)["items"] == []
    assert get(client, "/dead-letters/", admin_headers)["result"] == {"count": 0, "data": []}
    ot = get(client, "/events-over-time/", admin_headers, interval="hour")
    assert all(b["count"] == 0 for b in ot["buckets"]) and len(ot["buckets"]) in (24, 25)


def test_events_by_type_and_top_sources(client, admin_headers, seeded):
    by_type = {i["key"]: i["count"] for i in get(client, "/events-by-type/", admin_headers)["items"]}
    assert by_type == {"order.created": 7, "payment.failed": 3, "user.activity": 2, "custom.pending": 1, "custom.proc": 1}
    assert get(client, "/top-sources/", admin_headers, limit=2)["items"] == [{"key": "shop", "count": 7}, {"key": "billing", "count": 4}]
    assert len(get(client, "/events-by-type/", admin_headers, limit=1)["items"]) == 1


def test_events_over_time_gap_filled(client, admin_headers, seeded):
    hr = seeded["hour"]
    data = get(client, "/events-over-time/", admin_headers, interval="hour",
               **{"from": (hr - timedelta(hours=3)).isoformat(), "to": hr.isoformat()})
    b = data["buckets"]
    assert [x["count"] for x in b] == [0, 4, 10] and [x["processed"] for x in b] == [0, 2, 6] and [x["failed"] for x in b] == [0, 0, 3]
    assert datetime.fromisoformat(b[1]["bucket"]) == hr - timedelta(hours=2)
    day = get(client, "/events-over-time/", admin_headers, interval="day", event_type="order.created",
              **{"from": (seeded["now"] - timedelta(days=4)).isoformat()})
    assert sum(x["count"] for x in day["buckets"]) == 8


def test_range_validation(client, admin_headers):
    now = datetime.now(timezone.utc)
    r = client.get(f"{AN}/overview/", headers=admin_headers, params={"from": now.isoformat(), "to": (now - timedelta(hours=1)).isoformat()})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_RANGE"
    r = client.get(f"{AN}/events-over-time/", headers=admin_headers, params={"interval": "minute", "from": (now - timedelta(days=30)).isoformat()})
    assert r.status_code == 422 and r.json()["code"] == "TOO_MANY_BUCKETS"
    assert client.get(f"{AN}/events-over-time/", headers=admin_headers, params={"interval": "week"}).status_code == 422
    assert client.get(f"{AN}/overview/", headers=admin_headers, params={"status": "NOPE"}).status_code == 422


def test_failure_rates(client, admin_headers, seeded):
    items = {i["key"]: i for i in get(client, "/failure-rates/", admin_headers)["items"]}
    assert items["payment.failed"] == {"key": "payment.failed", "total": 3, "processed": 0, "failed": 3, "failure_rate": 1.0}
    assert items["order.created"]["failure_rate"] == 0.0 and items["order.created"]["total"] == 7
    assert items["custom.pending"]["failure_rate"] is None  # nothing finished -> undefined, not 0/0
    assert get(client, "/failure-rates/", admin_headers)["items"][0]["key"] == "payment.failed"  # worst first
    assert {i["key"]: i["failed"] for i in get(client, "/failure-rates/", admin_headers, group_by="source")["items"]}["billing"] == 3


def test_processing_latency_percentiles(client, admin_headers, seeded):
    o = get(client, "/processing-latency/", admin_headers, event_type="order.created")["overall"]
    assert o["samples"] == 6 and o["min_ms"] == 10 and o["max_ms"] == 100
    assert o["avg_ms"] == pytest.approx(41.667, abs=1e-3) and o["p50_ms"] == 35 and o["p95_ms"] == 87.5 and o["p99_ms"] == 97.5
    grouped = get(client, "/processing-latency/", admin_headers, group_by="event_type")
    assert {g["key"]: g["samples"] for g in grouped["groups"]} == {"order.created": 6, "user.activity": 2}
    assert grouped["overall"]["samples"] == 8  # the 3-day-old event is outside the window


def test_queue_status(client, admin_headers, seeded):
    q = get(client, "/queue-status/", admin_headers)
    assert q["queue_capacity"] == 100 and q["queue_size"] == 0 and q["saturated"] is False
    assert q["db_counts"]["PROCESSED"] == 9 and q["db_counts"]["DEAD_LETTER"] == 3 and q["db_counts"]["RETRYING"] == 1
    assert q["db_counts"]["FAILED"] == 0  # every status is present, even when zero


def test_dead_letters_filters_and_pagination(client, admin_headers, seeded):
    p1 = get(client, "/dead-letters/", admin_headers, limit=2, skip=0)["result"]
    p2 = get(client, "/dead-letters/", admin_headers, limit=2, skip=2)["result"]
    assert p1["count"] == 3 and len(p1["data"]) == 2 and len(p2["data"]) == 1
    assert [i["failure_reason"] for i in p1["data"] + p2["data"]] == ["boom 2", "boom 1", "boom 0"]  # newest first
    assert get(client, "/dead-letters/", admin_headers, resolution_status="OPEN")["result"]["count"] == 2
    assert get(client, "/dead-letters/", admin_headers, resolution_status="RESOLVED")["result"]["data"][0]["failure_reason"] == "boom 2"
    assert get(client, "/dead-letters/", admin_headers, source="shop")["result"]["count"] == 0
    assert get(client, "/dead-letters/", admin_headers, event_type="payment.failed")["result"]["count"] == 3
    assert client.get(f"{AN}/dead-letters/", headers=admin_headers, params={"limit": 0}).status_code == 422


def test_event_list_pagination_and_filters(client, admin_headers, seeded):
    first = client.get(EV, headers=admin_headers, params={"limit": 5, "skip": 0}).json()["result"]
    assert first["count"] == 15 and len(first["data"]) == 5
    ids = []
    for off in (0, 5, 10):
        ids += [e["id"] for e in client.get(EV, headers=admin_headers, params={"limit": 5, "skip": off}).json()["result"]["data"]]
    assert len(set(ids)) == 15  # no duplicates / gaps across pages
    assert client.get(EV, headers=admin_headers, params={"status": "DEAD_LETTER"}).json()["result"]["count"] == 3
    assert client.get(EV, headers=admin_headers, params={"status": ["DEAD_LETTER", "RETRYING"]}).json()["result"]["count"] == 4
    assert client.get(EV, headers=admin_headers, params={"from": (seeded["now"] - timedelta(days=1)).isoformat()}).json()["result"]["count"] == 14
    assert client.get(EV, headers=admin_headers, params={"limit": 1000}).status_code == 422
    assert client.get(EV, headers=admin_headers, params={"status": "WRONG"}).status_code == 422


def test_analytics_requires_permission(client, seeded):
    make_user("norole@example.com", "viewer")
    # strip the viewer role's permissions through the API as admin, then every analytics route must be denied
    make_user("admin2@example.com", "su", superuser=True)
    ah = login_headers(client, "admin2@example.com")
    vid = client.get("/api/roles/v1/role/", params={"code": "viewer"}, headers=ah).json()["result"]["data"][0]["id"]
    client.patch(f"/api/roles/v1/role/{vid}", headers=ah, json={"permission_ids": []})
    nh = login_headers(client, "norole@example.com")
    for p in ("/overview/", "/events-by-type/", "/events-over-time/", "/failure-rates/", "/processing-latency/",
              "/top-sources/", "/queue-status/", "/dead-letters/"):
        assert client.get(f"{AN}{p}", headers=nh).status_code == 403, p
