"""Event ingestion (validation, de-duplication), queries and reprocessing."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, RateLimitedError
from app.models.api_key import APIKey  # noqa: F401  (FK target registration)
from app.models.event import DeadLetterEvent, DeadLetterStatus, Event, EventStatus, ProcessingAttempt
from app.models.user import User
from app.schemas.event import EventIn, IngestItemResult
from app.services import audit_service
from app.services.api_key_service import ApiKeyPrincipal

MAX_DEPTH = 10


# --------------------------------------------------------------------------- validation
@dataclass
class Rejection:
    code: str
    message: str


def _inspect(value: Any, depth: int = 0) -> tuple[int, bool]:
    """Return (max nesting depth, contains NUL char). PostgreSQL JSONB cannot store \\u0000."""
    nul = False
    deepest = depth
    if isinstance(value, str):
        return depth, "\x00" in value
    if isinstance(value, dict):
        for k, v in value.items():
            if "\x00" in str(k):
                nul = True
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
    if "amount" in payload and not errs:
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


# Event-specific requirements for the known event families. Unknown types accept any payload.
TYPE_RULES: dict[str, Callable[[dict], list[str]]] = {
    "order.created": lambda p: _money(p, "order_id"),
    "payment.succeeded": lambda p: _money(p, "payment_id"),
    "payment.failed": lambda p: _money(p, "payment_id"),
    "user.activity": lambda p: _need(p, "user_id", "action"),
    "app.error": lambda p: _need(p, "service", "message"),
    "service.health": _health,
}


def validate_semantics(ev: EventIn, settings: Settings, now: datetime | None = None) -> Rejection | None:
    now = now or datetime.now(timezone.utc)
    if ev.schema_version not in settings.schema_versions:
        return Rejection("unsupported_schema_version",
                         f"schema_version '{ev.schema_version}' is not supported "
                         f"(supported: {', '.join(sorted(settings.schema_versions))})")
    if ev.timestamp > now + timedelta(seconds=settings.max_future_skew_seconds):
        return Rejection("invalid_timestamp", "timestamp is in the future")
    if ev.timestamp < now - timedelta(days=settings.max_event_age_days):
        return Rejection("invalid_timestamp", f"timestamp is older than {settings.max_event_age_days} days")
    for name, blob in (("payload", ev.payload), ("metadata", ev.metadata)):
        size = len(json.dumps(blob, separators=(",", ":"), ensure_ascii=False).encode())
        if size > settings.max_payload_bytes:
            return Rejection("payload_too_large", f"{name} is {size} bytes; limit is {settings.max_payload_bytes}")
        depth, nul = _inspect(blob)
        if depth > MAX_DEPTH:
            return Rejection("invalid_payload", f"{name} is nested deeper than {MAX_DEPTH} levels")
        if nul:
            return Rejection("invalid_payload", f"{name} contains a NUL character")
    rule = TYPE_RULES.get(ev.event_type)
    if rule and (errs := rule(ev.payload)):
        return Rejection("invalid_payload", "; ".join(errs))
    return None


def parse_and_validate(raw: Any, settings: Settings) -> EventIn | Rejection:
    try:
        ev = EventIn.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return Rejection("validation_error", f"{loc}: {first['msg']}" if loc else first["msg"])
    return validate_semantics(ev, settings) or ev


def tenant_check(ev: EventIn, principal: ApiKeyPrincipal) -> tuple[EventIn, Rejection | None]:
    """Enforce / apply the API key's tenant scope."""
    if principal.customer_id is None:
        return ev, None
    if ev.customer_id is None:
        return ev.model_copy(update={"customer_id": principal.customer_id}), None
    if ev.customer_id != principal.customer_id:
        return ev, Rejection("customer_mismatch", "customer_id does not match the API key's tenant")
    return ev, None


# --------------------------------------------------------------------------- ingestion
async def check_daily_quota(session: AsyncSession, principal: ApiKeyPrincipal, incoming: int) -> None:
    if principal.daily_event_quota is None:
        return
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used = await session.scalar(
        select(func.count(Event.id)).where(Event.api_key_id == principal.id, Event.received_at >= day_start)
    ) or 0
    if used + incoming > principal.daily_event_quota:
        tomorrow = day_start + timedelta(days=1)
        retry = max(1, int((tomorrow - datetime.now(timezone.utc)).total_seconds()))
        raise RateLimitedError(
            f"Daily event quota of {principal.daily_event_quota} exceeded", code="QUOTA_EXCEEDED",
            headers={"Retry-After": str(retry)},
        )


@dataclass
class IngestResult:
    results: list[IngestItemResult]
    new_ids: list[uuid.UUID]
    new_events: list[dict[str, Any]]

    @property
    def accepted(self) -> int:
        return sum(r.status == "accepted" for r in self.results)

    @property
    def duplicates(self) -> int:
        return sum(r.status == "duplicate" for r in self.results)

    @property
    def rejected(self) -> int:
        return sum(r.status == "rejected" for r in self.results)


async def insert_events(
    session: AsyncSession, principal: ApiKeyPrincipal, items: list[tuple[int, EventIn]]
) -> IngestResult:
    """Persist events atomically; duplicates are detected by the UNIQUE(event_id) constraint.

    `INSERT ... ON CONFLICT (event_id) DO UPDATE SET duplicate_count = duplicate_count + 1` is atomic, so
    concurrent submissions of the same event_id can never create two rows. `xmax = 0` identifies a fresh insert.
    """
    results: dict[int, IngestItemResult] = {}
    first_seen: dict[str, tuple[int, EventIn]] = {}
    repeats: dict[str, int] = {}
    for index, ev in items:
        if ev.event_id in first_seen:  # duplicate within the same batch
            repeats[ev.event_id] = repeats.get(ev.event_id, 0) + 1
            results[index] = IngestItemResult(index=index, event_id=ev.event_id, status="duplicate",
                                              code="duplicate_in_batch", message="event_id repeated in this batch")
        else:
            first_seen[ev.event_id] = (index, ev)

    new_ids: list[uuid.UUID] = []
    new_events: list[dict[str, Any]] = []
    if first_seen:
        rows = [
            {
                "id": uuid.uuid4(), "event_id": ev.event_id, "event_type": ev.event_type, "source": ev.source,
                "customer_id": ev.customer_id, "schema_version": ev.schema_version, "occurred_at": ev.timestamp,
                "payload": ev.payload, "event_metadata": ev.metadata, "status": EventStatus.RECEIVED.value,
                "api_key_id": principal.id,
            }
            for _, ev in first_seen.values()
        ]
        stmt = (
            pg_insert(Event).values(rows)
            .on_conflict_do_update(index_elements=[Event.event_id],
                                   set_={"duplicate_count": Event.duplicate_count + 1})
            .returning(Event.id, Event.event_id, literal_column("(xmax = 0)").label("inserted"))
        )
        by_event_id = {r.event_id: r for r in (await session.execute(stmt)).all()}
        for event_id, (index, ev) in first_seen.items():
            row = by_event_id[event_id]
            if row.inserted:
                results[index] = IngestItemResult(index=index, event_id=event_id, status="accepted", id=row.id)
                new_ids.append(row.id)
                new_events.append({"id": str(row.id), "event_id": event_id, "event_type": ev.event_type,
                                   "source": ev.source, "status": EventStatus.RECEIVED.value})
            else:
                results[index] = IngestItemResult(index=index, event_id=event_id, status="duplicate", id=row.id,
                                                  code="duplicate_event", message="event_id already received")
        for event_id, n in repeats.items():  # count in-batch repeats as duplicate submissions too
            await session.execute(update(Event).where(Event.event_id == event_id)
                                  .values(duplicate_count=Event.duplicate_count + n))
    await session.commit()
    return IngestResult([results[i] for i in sorted(results)], new_ids, new_events)


# --------------------------------------------------------------------------- queries
def _filters(*, status, event_type, source, customer_id, start, end, event_id=None) -> list:
    conds = []
    if status:
        conds.append(Event.status.in_(status))
    if event_type:
        conds.append(Event.event_type == event_type)
    if source:
        conds.append(Event.source == source)
    if customer_id:
        conds.append(Event.customer_id == customer_id)
    if start:
        conds.append(Event.received_at >= start)
    if end:
        conds.append(Event.received_at < end)
    if event_id:
        conds.append(Event.event_id == event_id)
    return conds


async def list_events(
    session: AsyncSession, *, status: list[str] | None, event_type: str | None, source: str | None,
    customer_id: str | None, start: datetime | None, end: datetime | None, event_id: str | None,
    limit: int, offset: int,
) -> tuple[list[Event], int]:
    conds = _filters(status=status, event_type=event_type, source=source, customer_id=customer_id,
                     start=start, end=end, event_id=event_id)
    total = await session.scalar(select(func.count(Event.id)).where(*conds)) or 0
    rows = (await session.scalars(
        select(Event).where(*conds).order_by(Event.received_at.desc(), Event.id).limit(limit).offset(offset)
    )).all()
    return list(rows), total


async def get_event_with_history(session: AsyncSession, event_pk: uuid.UUID):
    event = await session.get(Event, event_pk)
    if not event:
        raise NotFoundError("Event not found")
    attempts = (await session.scalars(
        select(ProcessingAttempt).where(ProcessingAttempt.event_id == event_pk).order_by(ProcessingAttempt.attempt_number)
    )).all()
    dead = (await session.scalars(
        select(DeadLetterEvent).where(DeadLetterEvent.event_id == event_pk).order_by(DeadLetterEvent.dead_lettered_at.desc())
    )).all()
    return event, list(attempts), list(dead)


# --------------------------------------------------------------------------- reprocessing
async def reprocess_event(
    session: AsyncSession, request: Request, actor: User, event_pk: uuid.UUID
) -> Event:
    """Reset a FAILED / DEAD_LETTER event to RECEIVED atomically (the caller then dispatches it)."""
    now = datetime.now(timezone.utc)
    updated = await session.execute(
        update(Event)
        .where(Event.id == event_pk, Event.status.in_([EventStatus.DEAD_LETTER.value, EventStatus.FAILED.value]))
        .values(status=EventStatus.RECEIVED.value, retry_count=0, completed_at=None, processing_started_at=None,
                next_retry_at=None, processing_duration_ms=None)
        .returning(Event.id)
        .execution_options(synchronize_session=False)
    )
    if updated.first() is None:
        await session.rollback()
        existing = await session.get(Event, event_pk)
        if existing is None:
            raise NotFoundError("Event not found")
        raise ConflictError(f"Event in status {existing.status} cannot be reprocessed; only FAILED/DEAD_LETTER events can",
                            code="NOT_REPROCESSABLE")
    await session.execute(
        update(DeadLetterEvent)
        .where(DeadLetterEvent.event_id == event_pk, DeadLetterEvent.resolution_status == DeadLetterStatus.OPEN.value)
        .values(resolution_status=DeadLetterStatus.REPROCESSED.value, resolved_at=now, resolved_by_user_id=actor.id,
                resolution_details="Manually reprocessed")
    )
    audit_service.record(session, action="event.reprocessed", actor=actor, request=request,
                         target_type="event", target_id=event_pk)
    await session.commit()
    event = await session.get(Event, event_pk)
    await session.refresh(event)
    return event


async def resolve_dead_letter(
    session: AsyncSession, request: Request, actor: User, dead_letter_id: uuid.UUID, details: str | None
) -> DeadLetterEvent:
    now = datetime.now(timezone.utc)
    row = (await session.execute(
        update(DeadLetterEvent)
        .where(DeadLetterEvent.id == dead_letter_id, DeadLetterEvent.resolution_status == DeadLetterStatus.OPEN.value)
        .values(resolution_status=DeadLetterStatus.RESOLVED.value, resolved_at=now, resolved_by_user_id=actor.id,
                resolution_details=details)
        .returning(DeadLetterEvent.id)
    )).first()
    if row is None:
        await session.rollback()
        if await session.get(DeadLetterEvent, dead_letter_id) is None:
            raise NotFoundError("Dead-letter record not found")
        raise ConflictError("Dead-letter record is already resolved", code="ALREADY_RESOLVED")
    audit_service.record(session, action="dead_letter.resolved", actor=actor, request=request,
                         target_type="dead_letter", target_id=dead_letter_id, details={"details": details})
    await session.commit()
    dl = await session.get(DeadLetterEvent, dead_letter_id)
    await session.refresh(dl)
    return dl
