# app/crud/event.py
"""Event ingestion (validation, de-duplication), queries and reprocessing."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import func, literal_column, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.crud import audit
from app.crud.api_key import ApiKeyPrincipal
from app.exceptions import AppError
from app.models import DeadLetterEvent, DeadLetterStatus, Event, EventStatus, ProcessingAttempt
from app.schemas.event import EventIn, IngestItemResult

MAX_DEPTH = 10


# ------------------------------------------------------------------ validation
@dataclass
class Rejection:
    code: str
    message: str


def _inspect(value: Any, depth: int = 0) -> tuple[int, bool]:
    """(max nesting depth, contains NUL). PostgreSQL JSONB cannot store \\u0000."""
    nul, deepest = False, depth
    if isinstance(value, str):
        return depth, "\x00" in value
    if isinstance(value, dict):
        for k, v in value.items():
            nul = nul or "\x00" in str(k)
            d, n = _inspect(v, depth + 1)
            deepest, nul = max(deepest, d), nul or n
    elif isinstance(value, list):
        for v in value:
            d, n = _inspect(v, depth + 1)
            deepest, nul = max(deepest, d), nul or n
    return deepest, nul


def _need(payload: dict, *fields: str) -> list[str]:
    return [f"payload.{f} is required" for f in fields if payload.get(f) in (None, "")]


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _money(payload: dict, id_field: str) -> list[str]:
    errs = _need(payload, id_field, "amount", "currency")
    if not errs:
        if not _is_number(payload["amount"]) or payload["amount"] < 0:
            errs.append("payload.amount must be a non-negative number")
        cur = payload["currency"]
        if not (isinstance(cur, str) and len(cur) == 3 and cur.isalpha()):
            errs.append("payload.currency must be a 3-letter code")
    return errs


def _health(payload: dict) -> list[str]:
    errs = _need(payload, "service", "status")
    if not errs and payload["status"] not in ("up", "degraded", "down"):
        errs.append("payload.status must be one of: up, degraded, down")
    return errs


# Event-specific payload requirements for the known event families; other types accept any object.
TYPE_RULES: dict[str, Callable[[dict], list[str]]] = {
    "order.created": lambda p: _money(p, "order_id"),
    "payment.succeeded": lambda p: _money(p, "payment_id"),
    "payment.failed": lambda p: _money(p, "payment_id"),
    "user.activity": lambda p: _need(p, "user_id", "action"),
    "app.error": lambda p: _need(p, "service", "message"),
    "service.health": _health,
}


def validate_semantics(ev: EventIn, now: datetime | None = None) -> Rejection | None:
    now = now or datetime.now(timezone.utc)
    if ev.schema_version not in settings.SCHEMA_VERSIONS:
        return Rejection("unsupported_schema_version",
                         f"schema_version '{ev.schema_version}' is not supported "
                         f"(supported: {', '.join(sorted(settings.SCHEMA_VERSIONS))})")
    if ev.timestamp > now + timedelta(seconds=settings.MAX_FUTURE_SKEW_SECONDS):
        return Rejection("invalid_timestamp", "timestamp is in the future")
    if ev.timestamp < now - timedelta(days=settings.MAX_EVENT_AGE_DAYS):
        return Rejection("invalid_timestamp", f"timestamp is older than {settings.MAX_EVENT_AGE_DAYS} days")
    for name, blob in (("payload", ev.payload), ("metadata", ev.metadata)):
        size = len(json.dumps(blob, separators=(",", ":"), ensure_ascii=False).encode())
        if size > settings.MAX_PAYLOAD_BYTES:
            return Rejection("payload_too_large", f"{name} is {size} bytes; limit is {settings.MAX_PAYLOAD_BYTES}")
        depth, nul = _inspect(blob)
        if depth > MAX_DEPTH:
            return Rejection("invalid_payload", f"{name} is nested deeper than {MAX_DEPTH} levels")
        if nul:
            return Rejection("invalid_payload", f"{name} contains a NUL character")
    rule = TYPE_RULES.get(ev.event_type)
    if rule and (errs := rule(ev.payload)):
        return Rejection("invalid_payload", "; ".join(errs))
    return None


def parse_and_validate(raw: Any) -> EventIn | Rejection:
    try:
        ev = EventIn.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return Rejection("validation_error", f"{loc}: {first['msg']}" if loc else first["msg"])
    return validate_semantics(ev) or ev


def tenant_check(ev: EventIn, principal: ApiKeyPrincipal) -> tuple[EventIn, Rejection | None]:
    """Apply / enforce the API key's tenant lock."""
    if principal.customer_id is None:
        return ev, None
    if ev.customer_id is None:
        return ev.model_copy(update={"customer_id": principal.customer_id}), None
    if ev.customer_id != principal.customer_id:
        return ev, Rejection("customer_mismatch", "customer_id does not match the API key's tenant")
    return ev, None


# ------------------------------------------------------------------ ingestion
def check_daily_quota(db: Session, principal: ApiKeyPrincipal, incoming: int) -> None:
    if principal.daily_event_quota is None:
        return
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.query(func.count(Event.id)).filter(Event.api_key_id == principal.id, Event.received_at >= day_start).scalar() or 0
    if used + incoming > principal.daily_event_quota:
        retry = max(1, int((day_start + timedelta(days=1) - datetime.now(timezone.utc)).total_seconds()))
        raise AppError(429, f"Daily event quota of {principal.daily_event_quota} exceeded", "QUOTA_EXCEEDED",
                       {"Retry-After": str(retry)})


@dataclass
class IngestResult:
    results: list[IngestItemResult]
    new_ids: list[int]
    new_events: list[dict[str, Any]]


def insert_events(db: Session, principal: ApiKeyPrincipal, items: list[tuple[int, EventIn]]) -> IngestResult:
    """Persist events atomically; duplicates are detected by UNIQUE(event_id).

    `INSERT ... ON CONFLICT (event_id) DO UPDATE SET duplicate_count = duplicate_count + 1` is atomic, so concurrent
    submissions of the same event_id can never create two rows; `xmax = 0` identifies a freshly inserted row.
    """
    results: dict[int, IngestItemResult] = {}
    first_seen: dict[str, tuple[int, EventIn]] = {}
    repeats: dict[str, int] = {}
    for index, ev in items:
        if ev.event_id in first_seen:  # repeated inside the same batch
            repeats[ev.event_id] = repeats.get(ev.event_id, 0) + 1
            results[index] = IngestItemResult(index=index, event_id=ev.event_id, status="duplicate",
                                              code="duplicate_in_batch", message="event_id repeated in this batch")
        else:
            first_seen[ev.event_id] = (index, ev)

    new_ids: list[int] = []
    new_events: list[dict[str, Any]] = []
    if first_seen:
        # Sorted so concurrent overlapping batches lock rows in the same order (no deadlocks).
        rows = [
            {"event_id": ev.event_id, "event_type": ev.event_type, "source": ev.source, "customer_id": ev.customer_id,
             "schema_version": ev.schema_version, "occurred_at": ev.timestamp, "payload": ev.payload,
             "event_metadata": ev.metadata, "status": EventStatus.RECEIVED.value, "api_key_id": principal.id}
            for _, ev in sorted(first_seen.values(), key=lambda t: t[1].event_id)
        ]
        stmt = (pg_insert(Event).values(rows)
                .on_conflict_do_update(index_elements=[Event.event_id],
                                       set_={"duplicate_count": Event.duplicate_count + 1})
                .returning(Event.id, Event.event_id, literal_column("(xmax = 0)").label("inserted")))
        by_event_id = {r.event_id: r for r in db.execute(stmt).all()}
        for event_id, (index, ev) in first_seen.items():
            row = by_event_id[event_id]
            if row.inserted:
                results[index] = IngestItemResult(index=index, event_id=event_id, status="accepted", id=row.id)
                new_ids.append(row.id)
                new_events.append({"id": row.id, "event_id": event_id, "event_type": ev.event_type,
                                   "source": ev.source, "status": EventStatus.RECEIVED.value})
            else:
                results[index] = IngestItemResult(index=index, event_id=event_id, status="duplicate", id=row.id,
                                                  code="duplicate_event", message="event_id already received")
        for event_id, n in sorted(repeats.items()):
            db.execute(update(Event).where(Event.event_id == event_id).values(duplicate_count=Event.duplicate_count + n))
    db.commit()
    return IngestResult([results[i] for i in sorted(results)], new_ids, new_events)


# ------------------------------------------------------------------ queries
def list_events(db: Session, *, status: list[str] | None, event_type: str | None, source: str | None,
                customer_id: str | None, start: datetime | None, end: datetime | None, event_id: str | None,
                skip: int, limit: int) -> tuple[list[Event], int]:
    q = db.query(Event)
    if status:
        q = q.filter(Event.status.in_(status))
    if event_type:
        q = q.filter(Event.event_type == event_type)
    if source:
        q = q.filter(Event.source == source)
    if customer_id:
        q = q.filter(Event.customer_id == customer_id)
    if start:
        q = q.filter(Event.received_at >= start)
    if end:
        q = q.filter(Event.received_at < end)
    if event_id:
        q = q.filter(Event.event_id == event_id)
    total = q.with_entities(func.count(Event.id)).scalar() or 0
    rows = q.order_by(Event.received_at.desc(), Event.id.desc()).offset(skip).limit(limit).all()
    return rows, total


def get_event_with_history(db: Session, event_pk: int):
    event = db.get(Event, event_pk)
    if not event:
        raise AppError(404, f"Event with id {event_pk} not found")
    attempts = (db.query(ProcessingAttempt).filter(ProcessingAttempt.event_id == event_pk)
                .order_by(ProcessingAttempt.attempt_number).all())
    dead = (db.query(DeadLetterEvent).filter(DeadLetterEvent.event_id == event_pk)
            .order_by(DeadLetterEvent.dead_lettered_at.desc(), DeadLetterEvent.id.desc()).all())
    return event, attempts, dead


# ------------------------------------------------------------------ operator actions
def reprocess_event(db: Session, request: Request, actor: models.User, event_pk: int) -> Event:
    """Reset a FAILED / DEAD_LETTER event to RECEIVED atomically (the caller then dispatches it)."""
    now = datetime.now(timezone.utc)
    updated = db.execute(
        update(Event)
        .where(Event.id == event_pk, Event.status.in_([EventStatus.DEAD_LETTER.value, EventStatus.FAILED.value]))
        .values(status=EventStatus.RECEIVED.value, retry_count=0, completed_at=None, processing_started_at=None,
                next_retry_at=None, processing_duration_ms=None)
        .returning(Event.id).execution_options(synchronize_session=False)
    ).first()
    if updated is None:
        db.rollback()
        existing = db.get(Event, event_pk)
        if existing is None:
            raise AppError(404, f"Event with id {event_pk} not found")
        raise AppError(409, f"Event in status {existing.status} cannot be reprocessed; only FAILED/DEAD_LETTER can",
                       "NOT_REPROCESSABLE")
    db.execute(update(DeadLetterEvent)
               .where(DeadLetterEvent.event_id == event_pk, DeadLetterEvent.resolution_status == DeadLetterStatus.OPEN.value)
               .values(resolution_status=DeadLetterStatus.REPROCESSED.value, resolved_at=now,
                       resolved_by_user_id=actor.id, resolution_details="Manually reprocessed"))
    audit.record(db, action="event.reprocessed", actor=actor, request=request, target_type="event", target_id=event_pk)
    db.commit()
    event = db.get(Event, event_pk)
    db.refresh(event)
    return event


def resolve_dead_letter(db: Session, request: Request, actor: models.User, dead_letter_id: int,
                        details: str | None) -> DeadLetterEvent:
    row = db.execute(
        update(DeadLetterEvent)
        .where(DeadLetterEvent.id == dead_letter_id, DeadLetterEvent.resolution_status == DeadLetterStatus.OPEN.value)
        .values(resolution_status=DeadLetterStatus.RESOLVED.value, resolved_at=datetime.now(timezone.utc),
                resolved_by_user_id=actor.id, resolution_details=details)
        .returning(DeadLetterEvent.id)
    ).first()
    if row is None:
        db.rollback()
        if db.get(DeadLetterEvent, dead_letter_id) is None:
            raise AppError(404, f"Dead-letter record with id {dead_letter_id} not found")
        raise AppError(409, "Dead-letter record is already resolved", "ALREADY_RESOLVED")
    audit.record(db, action="dead_letter.resolved", actor=actor, request=request, target_type="dead_letter",
                 target_id=dead_letter_id, details={"details": details})
    db.commit()
    dl = db.get(DeadLetterEvent, dead_letter_id)
    db.refresh(dl)
    return dl
