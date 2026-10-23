"""Event processing: handler registry plus the DB state transitions of the pipeline.

State machine:
  RECEIVED -> QUEUED -> PROCESSING -> PROCESSED
  PROCESSING -> RETRYING -> PROCESSING ...
  retries exhausted / non-retryable -> FAILED -> DEAD_LETTER   (FAILED is transient inside one transaction)

Every transition is a conditional UPDATE so two workers can never process the same event concurrently.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.event import (
    CLAIMABLE_STATUSES,
    AttemptOutcome,
    DeadLetterEvent,
    Event,
    EventStatus,
    ProcessingAttempt,
)


class ProcessingError(Exception):
    """Retryable processing failure."""


class NonRetryableProcessingError(ProcessingError):
    """Permanent failure: skip retries and dead-letter immediately."""


@dataclass(frozen=True)
class EventContext:
    id: uuid.UUID
    event_id: str
    event_type: str
    source: str
    customer_id: str | None
    payload: dict[str, Any]
    metadata: dict[str, Any]
    attempt_number: int
    retry_count: int


Handler = Callable[[EventContext], Awaitable[None]]


async def default_handler(ctx: EventContext) -> None:
    """Default business logic hook. Register type-specific handlers on the HandlerRegistry.

    The default accepts the event as-is; real deployments would enrich, forward or aggregate here.
    """
    await asyncio.sleep(0)


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, event_type: str, handler: Handler) -> None:
        self._handlers[event_type] = handler

    def get(self, event_type: str) -> Handler:
        return self._handlers.get(event_type, default_handler)


_SECRET_PATTERNS = [
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "Bearer [REDACTED]"),
    (re.compile(r"sp_[0-9a-f]{8}_[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"postgres(?:ql)?(\+\w+)?://\S+"), "[REDACTED_DSN]"),
]


def sanitize_error(exc: BaseException | str, limit: int = 500) -> str:
    """Single-line, secret-scrubbed, length-bounded error text (no tracebacks)."""
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    text = " ".join(text.split())
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text[:limit]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def claim_event(session: AsyncSession, event_pk: uuid.UUID) -> EventContext | None:
    """Atomically move an event to PROCESSING. Returns None if another worker/state got there first."""
    now = _now()
    row = (
        await session.execute(
            update(Event)
            .where(Event.id == event_pk, Event.status.in_([s.value for s in CLAIMABLE_STATUSES]))
            .values(status=EventStatus.PROCESSING.value, processing_started_at=now, next_retry_at=None)
            .returning(Event.id, Event.event_id, Event.event_type, Event.source, Event.customer_id,
                       Event.payload, Event.event_metadata, Event.retry_count)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if row is None:
        await session.rollback()
        return None
    last = await session.scalar(
        select(func.coalesce(func.max(ProcessingAttempt.attempt_number), 0)).where(ProcessingAttempt.event_id == event_pk)
    )
    attempt_no = (last or 0) + 1
    session.add(ProcessingAttempt(event_id=event_pk, attempt_number=attempt_no, started_at=now,
                                  outcome=AttemptOutcome.RUNNING.value))
    await session.commit()
    return EventContext(
        id=row.id, event_id=row.event_id, event_type=row.event_type, source=row.source,
        customer_id=row.customer_id, payload=row.payload, metadata=row.event_metadata,
        attempt_number=attempt_no, retry_count=row.retry_count,
    )


async def mark_success(session: AsyncSession, event_pk: uuid.UUID, duration_ms: float) -> bool:
    now = _now()
    result = await session.execute(
        update(Event)
        .where(Event.id == event_pk, Event.status == EventStatus.PROCESSING.value)
        .values(status=EventStatus.PROCESSED.value, completed_at=now, processing_duration_ms=duration_ms, last_error=None)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        await session.rollback()
        return False
    await session.execute(
        update(ProcessingAttempt)
        .where(ProcessingAttempt.event_id == event_pk, ProcessingAttempt.outcome == AttemptOutcome.RUNNING.value)
        .values(outcome=AttemptOutcome.SUCCESS.value, completed_at=now, duration_ms=duration_ms)
    )
    await session.commit()
    return True


def retry_delay(settings: Settings, retry_number: int) -> float:
    """Exponential backoff: base * 2^(n-1), capped. `retry_number` starts at 1."""
    return min(settings.event_retry_base_delay_seconds * (2 ** (retry_number - 1)), settings.event_retry_max_delay_seconds)


async def register_failure(
    session: AsyncSession,
    settings: Settings,
    event_pk: uuid.UUID,
    error: str,
    *,
    retryable: bool,
    duration_ms: float | None,
    outcome: AttemptOutcome = AttemptOutcome.FAILED,
) -> EventStatus | None:
    """Record a failed/interrupted attempt; schedule a retry or dead-letter the event.

    Returns the new event status, or None if the event was not in PROCESSING (nothing changed).
    """
    now = _now()
    row = (
        await session.execute(
            select(Event.status, Event.retry_count).where(Event.id == event_pk).with_for_update()
        )
    ).first()
    if row is None or row.status != EventStatus.PROCESSING.value:
        await session.rollback()
        return None

    error = sanitize_error(error)
    if retryable and row.retry_count < settings.event_max_retries:
        new_count = row.retry_count + 1
        new_status = EventStatus.RETRYING
        await session.execute(
            update(Event).where(Event.id == event_pk).values(
                status=new_status.value, retry_count=new_count, last_error=error, processing_duration_ms=duration_ms,
                next_retry_at=now + timedelta(seconds=retry_delay(settings, new_count)),
            )
        )
    else:
        new_status = EventStatus.DEAD_LETTER  # passes through FAILED within this transaction
        await session.execute(
            update(Event).where(Event.id == event_pk).values(
                status=new_status.value, last_error=error, processing_duration_ms=duration_ms,
                completed_at=now, next_retry_at=None,
            )
        )
        session.add(DeadLetterEvent(event_id=event_pk, failure_reason=error, retry_count=row.retry_count))
    await session.execute(
        update(ProcessingAttempt)
        .where(ProcessingAttempt.event_id == event_pk, ProcessingAttempt.outcome == AttemptOutcome.RUNNING.value)
        .values(outcome=outcome.value, completed_at=now, duration_ms=duration_ms, error=error)
    )
    await session.commit()
    return new_status


async def recover_interrupted(session: AsyncSession, settings: Settings) -> int:
    """Startup recovery: events left in PROCESSING were interrupted (crash / kill). Re-schedule them."""
    ids = list((await session.scalars(select(Event.id).where(Event.status == EventStatus.PROCESSING.value))).all())
    for event_pk in ids:
        await register_failure(session, settings, event_pk, "Processing interrupted (application restart)",
                               retryable=True, duration_ms=None, outcome=AttemptOutcome.INTERRUPTED)
    return len(ids)


async def collect_dispatchable(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    """Oldest events that should be in the queue: RECEIVED/QUEUED, or RETRYING whose delay has elapsed."""
    now = _now()
    stmt = (
        select(Event.id)
        .where(or_(
            Event.status.in_([EventStatus.RECEIVED.value, EventStatus.QUEUED.value]),
            and_(Event.status == EventStatus.RETRYING.value, Event.next_retry_at <= now),
        ))
        .order_by(Event.received_at, Event.id)
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def mark_queued(session: AsyncSession, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    await session.execute(
        update(Event).where(Event.id.in_(ids), Event.status == EventStatus.RECEIVED.value)
        .values(status=EventStatus.QUEUED.value).execution_options(synchronize_session=False)
    )
    await session.commit()
