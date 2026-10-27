# app/crud/processing.py
"""Event processing: handler registry + the DB state transitions of the pipeline.

  RECEIVED -> QUEUED -> PROCESSING -> PROCESSED
  PROCESSING -> RETRYING -> PROCESSING ...
  retries exhausted / non-retryable -> FAILED -> DEAD_LETTER   (FAILED is transient inside one transaction)

Every transition is a conditional UPDATE, so two workers can never process the same event at once.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AttemptOutcome, DeadLetterEvent, Event, EventStatus, ProcessingAttempt
from app.models.event import CLAIMABLE_STATUSES


class ProcessingError(Exception):
    """Retryable processing failure."""


class NonRetryableProcessingError(ProcessingError):
    """Permanent failure: skip retries and dead-letter immediately."""


@dataclass(frozen=True)
class EventContext:
    id: int
    event_id: str
    event_type: str
    source: str
    customer_id: str | None
    payload: dict[str, Any]
    metadata: dict[str, Any]
    attempt_number: int
    retry_count: int


Handler = Callable[[EventContext], Any]  # sync `def` or `async def`


def default_handler(ctx: EventContext) -> None:
    """Default business-logic hook: accepts the event unchanged. Register type-specific handlers on the registry."""
    return None


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
    """Single-line, secret-scrubbed, length-bounded error text (never a traceback)."""
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    text = " ".join(text.split())
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text[:limit]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def claim_event(db: Session, event_pk: int) -> EventContext | None:
    """Atomically move an event to PROCESSING; None if another worker (or state) got there first."""
    now = _now()
    row = db.execute(
        update(Event)
        .where(Event.id == event_pk, Event.status.in_([s.value for s in CLAIMABLE_STATUSES]))
        .values(status=EventStatus.PROCESSING.value, processing_started_at=now, next_retry_at=None)
        .returning(Event.id, Event.event_id, Event.event_type, Event.source, Event.customer_id, Event.payload,
                   Event.event_metadata, Event.retry_count)
        .execution_options(synchronize_session=False)
    ).first()
    if row is None:
        db.rollback()
        return None
    last = db.scalar(select(func.coalesce(func.max(ProcessingAttempt.attempt_number), 0))
                     .where(ProcessingAttempt.event_id == event_pk)) or 0
    db.add(ProcessingAttempt(event_id=event_pk, attempt_number=last + 1, started_at=now,
                             outcome=AttemptOutcome.RUNNING.value))
    db.commit()
    return EventContext(id=row.id, event_id=row.event_id, event_type=row.event_type, source=row.source,
                        customer_id=row.customer_id, payload=row.payload, metadata=row.event_metadata,
                        attempt_number=last + 1, retry_count=row.retry_count)


def _attempt_is_current(db: Session, event_pk: int, attempt_number: int | None) -> bool:
    """Fencing: only the attempt that is still RUNNING may finish the event. A straggler thread that was
    abandoned at shutdown (and whose attempt was marked INTERRUPTED / superseded) can never overwrite newer state."""
    if attempt_number is None:
        return True
    return db.scalar(select(ProcessingAttempt.id).where(
        ProcessingAttempt.event_id == event_pk, ProcessingAttempt.attempt_number == attempt_number,
        ProcessingAttempt.outcome == AttemptOutcome.RUNNING.value)) is not None


def mark_success(db: Session, event_pk: int, attempt_number: int, duration_ms: float) -> bool:
    now = _now()
    row = db.execute(select(Event.status).where(Event.id == event_pk).with_for_update()).first()
    if row is None or row.status != EventStatus.PROCESSING.value or not _attempt_is_current(db, event_pk, attempt_number):
        db.rollback()
        return False
    db.execute(update(Event).where(Event.id == event_pk)
               .values(status=EventStatus.PROCESSED.value, completed_at=now, processing_duration_ms=duration_ms,
                       last_error=None))
    db.execute(update(ProcessingAttempt)
               .where(ProcessingAttempt.event_id == event_pk, ProcessingAttempt.attempt_number == attempt_number)
               .values(outcome=AttemptOutcome.SUCCESS.value, completed_at=now, duration_ms=duration_ms))
    db.commit()
    return True


def retry_delay(retry_number: int) -> float:
    """Exponential backoff base * 2^(n-1), capped. `retry_number` starts at 1."""
    return min(settings.EVENT_RETRY_BASE_DELAY_SECONDS * (2 ** (retry_number - 1)), settings.EVENT_RETRY_MAX_DELAY_SECONDS)


def register_failure(db: Session, event_pk: int, error: str, *, retryable: bool, duration_ms: float | None,
                     outcome: AttemptOutcome = AttemptOutcome.FAILED,
                     attempt_number: int | None = None) -> EventStatus | None:
    """Record a failed/interrupted attempt; schedule a retry or dead-letter the event.

    Returns the new status, or None if the event was not in PROCESSING (nothing changed).
    """
    now = _now()
    row = db.execute(select(Event.status, Event.retry_count).where(Event.id == event_pk).with_for_update()).first()
    if row is None or row.status != EventStatus.PROCESSING.value or not _attempt_is_current(db, event_pk, attempt_number):
        db.rollback()
        return None
    error = sanitize_error(error)
    if retryable and row.retry_count < settings.EVENT_MAX_RETRIES:
        new_count = row.retry_count + 1
        new_status = EventStatus.RETRYING
        db.execute(update(Event).where(Event.id == event_pk).values(
            status=new_status.value, retry_count=new_count, last_error=error, processing_duration_ms=duration_ms,
            next_retry_at=now + timedelta(seconds=retry_delay(new_count))))
    else:
        new_status = EventStatus.DEAD_LETTER  # passes through FAILED inside this transaction
        db.execute(update(Event).where(Event.id == event_pk).values(
            status=new_status.value, last_error=error, processing_duration_ms=duration_ms, completed_at=now,
            next_retry_at=None))
        db.add(DeadLetterEvent(event_id=event_pk, failure_reason=error, retry_count=row.retry_count))
    db.execute(update(ProcessingAttempt)
               .where(ProcessingAttempt.event_id == event_pk, ProcessingAttempt.outcome == AttemptOutcome.RUNNING.value)
               .values(outcome=outcome.value, completed_at=now, duration_ms=duration_ms, error=error))
    db.commit()
    return new_status


def recover_interrupted(db: Session) -> int:
    """Startup recovery: events left in PROCESSING were interrupted (crash/kill) - re-schedule them."""
    ids = [i for (i,) in db.query(Event.id).filter(Event.status == EventStatus.PROCESSING.value).all()]
    for event_pk in ids:
        register_failure(db, event_pk, "Processing interrupted (application restart)", retryable=True,
                         duration_ms=None, outcome=AttemptOutcome.INTERRUPTED)
    return len(ids)


def collect_dispatchable(db: Session, limit: int) -> list[int]:
    """Oldest events that should be queued: RECEIVED/QUEUED, or RETRYING whose delay has elapsed."""
    now = _now()
    stmt = (select(Event.id)
            .where(or_(Event.status.in_([EventStatus.RECEIVED.value, EventStatus.QUEUED.value]),
                       and_(Event.status == EventStatus.RETRYING.value, Event.next_retry_at <= now)))
            .order_by(Event.received_at, Event.id).limit(limit))
    return list(db.scalars(stmt).all())


def mark_queued(db: Session, ids: list[int]) -> None:
    if not ids:
        return
    db.execute(update(Event).where(Event.id.in_(ids), Event.status == EventStatus.RECEIVED.value)
               .values(status=EventStatus.QUEUED.value).execution_options(synchronize_session=False))
    db.commit()
