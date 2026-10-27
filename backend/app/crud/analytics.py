# app/crud/analytics.py
"""Analytics computed entirely with PostgreSQL aggregations (never by loading events into Python).

Metric definitions
  window                [start, end) over `received_at`; default last 24h
  total_received        events received in the window
  processed / failed / pending / processing   status = PROCESSED / (FAILED, DEAD_LETTER) / (RECEIVED, QUEUED,
                        RETRYING) / PROCESSING
  success_rate          processed / (processed + failed)  -> None when no event has finished
  failure_rate          failed    / (processed + failed)  -> None when no event has finished
  events_per_minute     total_received / window length in minutes
  duplicate_submissions sum(duplicate_count) of events received in the window
  latency               processing_duration_ms of PROCESSED events (final successful attempt)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import AppError
from app.models import DeadLetterEvent, DeadLetterStatus, Event, EventStatus
from app.models.event import FAILED_STATUSES, PENDING_STATUSES
from app.schemas import analytics as s

PROCESSED = EventStatus.PROCESSED.value
FAILED = [x.value for x in FAILED_STATUSES]
PENDING = [x.value for x in PENDING_STATUSES]
MAX_BUCKETS = 2000
GROUP_COLUMNS = {"event_type": Event.event_type, "source": Event.source, "customer_id": Event.customer_id}
INTERVALS = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1), "day": timedelta(days=1)}


def resolve_window(start: datetime | None, end: datetime | None) -> s.TimeWindow:
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(hours=24)
    if start >= end:
        raise AppError(422, "'from' must be earlier than 'to'", "INVALID_RANGE")
    return s.TimeWindow(start=start, end=end, minutes=(end - start).total_seconds() / 60)


def _conds(w: s.TimeWindow, event_type=None, source=None, customer_id=None, status=None) -> list:
    conds = [Event.received_at >= w.start, Event.received_at < w.end]
    if event_type:
        conds.append(Event.event_type == event_type)
    if source:
        conds.append(Event.source == source)
    if customer_id:
        conds.append(Event.customer_id == customer_id)
    if status:
        conds.append(Event.status.in_(status))
    return conds


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _r(v) -> float | None:
    return None if v is None else round(float(v), 3)


def overview(db: Session, w: s.TimeWindow, **f) -> s.OverviewResponse:
    conds = _conds(w, **f)
    row = db.execute(select(
        func.count(Event.id),
        func.count(Event.id).filter(Event.status == PROCESSED),
        func.count(Event.id).filter(Event.status.in_(FAILED)),
        func.count(Event.id).filter(Event.status.in_(PENDING)),
        func.count(Event.id).filter(Event.status == EventStatus.PROCESSING.value),
        func.coalesce(func.sum(Event.duplicate_count), 0),
        func.coalesce(func.sum(Event.retry_count), 0),
        func.avg(Event.processing_duration_ms).filter(Event.status == PROCESSED),
    ).where(*conds)).one()
    total, processed, failed, pending, processing, dups, retries, avg_ms = row
    dl_open = db.scalar(select(func.count(DeadLetterEvent.id)).join(Event, Event.id == DeadLetterEvent.event_id)
                        .where(*conds, DeadLetterEvent.resolution_status == DeadLetterStatus.OPEN.value)) or 0
    finished = processed + failed
    return s.OverviewResponse(
        window=w, total_received=total, processed=processed, failed=failed, pending=pending, processing=processing,
        duplicate_submissions=int(dups), retries_total=int(retries), dead_letters_open=dl_open,
        events_per_minute=round(total / w.minutes, 4) if w.minutes > 0 else 0.0,
        success_rate=_rate(processed, finished), failure_rate=_rate(failed, finished),
        avg_processing_latency_ms=_r(avg_ms))


def events_by_type(db: Session, w: s.TimeWindow, limit: int, **f) -> s.EventsByTypeResponse:
    rows = db.execute(select(Event.event_type, func.count(Event.id)).where(*_conds(w, **f))
                      .group_by(Event.event_type).order_by(func.count(Event.id).desc(), Event.event_type).limit(limit)).all()
    return s.EventsByTypeResponse(window=w, items=[s.CountItem(key=r[0], count=r[1]) for r in rows])


def _floor(dt: datetime, interval: str) -> datetime:
    dt = dt.astimezone(timezone.utc)
    if interval == "minute":
        return dt.replace(second=0, microsecond=0)
    if interval == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def events_over_time(db: Session, w: s.TimeWindow, interval: str, **f) -> s.EventsOverTimeResponse:
    step = INTERVALS[interval]
    first, last = _floor(w.start, interval), _floor(w.end - timedelta(microseconds=1), interval)
    if (last - first) / step + 1 > MAX_BUCKETS:
        raise AppError(422, f"Range too large for '{interval}' buckets (max {MAX_BUCKETS}); use a coarser interval",
                       "TOO_MANY_BUCKETS")
    bucket = func.date_trunc(interval, Event.received_at).label("bucket")
    rows = db.execute(select(bucket, func.count(Event.id), func.count(Event.id).filter(Event.status == PROCESSED),
                             func.count(Event.id).filter(Event.status.in_(FAILED)))
                      .where(*_conds(w, **f)).group_by(bucket).order_by(bucket)).all()
    data = {r[0].astimezone(timezone.utc): r for r in rows}
    buckets, cur = [], first
    while cur <= last:  # gap-fill so charts get a continuous series
        r = data.get(cur)
        buckets.append(s.TimeBucket(bucket=cur, count=r[1] if r else 0, processed=r[2] if r else 0, failed=r[3] if r else 0))
        cur += step
    return s.EventsOverTimeResponse(window=w, interval=interval, buckets=buckets)


def failure_rates(db: Session, w: s.TimeWindow, group_by: str, limit: int, **f) -> s.FailureRatesResponse:
    col = GROUP_COLUMNS[group_by]
    failed_n = func.count(Event.id).filter(Event.status.in_(FAILED))
    rows = db.execute(select(col, func.count(Event.id), func.count(Event.id).filter(Event.status == PROCESSED), failed_n)
                      .where(*_conds(w, **f)).group_by(col)
                      .order_by(failed_n.desc(), func.count(Event.id).desc(), col).limit(limit)).all()
    return s.FailureRatesResponse(window=w, group_by=group_by, items=[
        s.FailureRateItem(key=r[0], total=r[1], processed=r[2], failed=r[3], failure_rate=_rate(r[3], r[2] + r[3]))
        for r in rows])


def _latency_cols():
    d = Event.processing_duration_ms
    return (func.count(d), func.avg(d), func.min(d), func.percentile_cont(0.5).within_group(d),
            func.percentile_cont(0.95).within_group(d), func.percentile_cont(0.99).within_group(d), func.max(d))


def _lat(key, r) -> s.LatencyStats:
    return s.LatencyStats(key=key, samples=r[0], avg_ms=_r(r[1]), min_ms=_r(r[2]), p50_ms=_r(r[3]), p95_ms=_r(r[4]),
                          p99_ms=_r(r[5]), max_ms=_r(r[6]))


def processing_latency(db: Session, w: s.TimeWindow, group_by: str | None, **f) -> s.LatencyResponse:
    f = {**f, "status": [PROCESSED]}
    base = [*_conds(w, **f), Event.processing_duration_ms.is_not(None)]
    overall = _lat(None, db.execute(select(*_latency_cols()).where(*base)).one())
    groups: list[s.LatencyStats] = []
    if group_by:
        col = GROUP_COLUMNS[group_by]
        rows = db.execute(select(col, *_latency_cols()).where(*base).group_by(col)
                          .order_by(func.count(Event.processing_duration_ms).desc()).limit(100)).all()
        groups = [_lat(r[0], r[1:]) for r in rows]
    return s.LatencyResponse(window=w, overall=overall, groups=groups)


def top_sources(db: Session, w: s.TimeWindow, limit: int, **f) -> s.TopSourcesResponse:
    rows = db.execute(select(Event.source, func.count(Event.id)).where(*_conds(w, **f)).group_by(Event.source)
                      .order_by(func.count(Event.id).desc(), Event.source).limit(limit)).all()
    return s.TopSourcesResponse(window=w, items=[s.CountItem(key=r[0], count=r[1]) for r in rows])


def status_counts(db: Session) -> dict[str, int]:
    counts = {st.value: 0 for st in EventStatus}
    counts.update({r[0]: r[1] for r in db.execute(select(Event.status, func.count(Event.id)).group_by(Event.status)).all()})
    return counts


def list_dead_letters(db: Session, w: s.TimeWindow, *, resolution_status: str | None, event_type: str | None,
                      source: str | None, skip: int, limit: int) -> tuple[list[s.DeadLetterItem], int]:
    conds = [DeadLetterEvent.dead_lettered_at >= w.start, DeadLetterEvent.dead_lettered_at < w.end]
    if resolution_status:
        conds.append(DeadLetterEvent.resolution_status == resolution_status)
    if event_type:
        conds.append(Event.event_type == event_type)
    if source:
        conds.append(Event.source == source)
    total = db.scalar(select(func.count(DeadLetterEvent.id)).join(Event, Event.id == DeadLetterEvent.event_id)
                      .where(*conds)) or 0
    rows = db.execute(select(DeadLetterEvent, Event).join(Event, Event.id == DeadLetterEvent.event_id).where(*conds)
                      .order_by(DeadLetterEvent.dead_lettered_at.desc(), DeadLetterEvent.id.desc())
                      .offset(skip).limit(limit)).all()
    return [s.DeadLetterItem(
        id=dl.id, event_pk=ev.id, event_id=ev.event_id, event_type=ev.event_type, source=ev.source,
        customer_id=ev.customer_id, failure_reason=dl.failure_reason, retry_count=dl.retry_count,
        dead_lettered_at=dl.dead_lettered_at, resolution_status=dl.resolution_status, resolved_at=dl.resolved_at,
        resolution_details=dl.resolution_details) for dl, ev in rows], total
