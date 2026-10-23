import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class EventStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    RETRYING = "RETRYING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


PENDING_STATUSES = (EventStatus.RECEIVED, EventStatus.QUEUED, EventStatus.RETRYING)
FAILED_STATUSES = (EventStatus.FAILED, EventStatus.DEAD_LETTER)
CLAIMABLE_STATUSES = (EventStatus.RECEIVED, EventStatus.QUEUED, EventStatus.RETRYING)


def _in_list(values: type[enum.Enum]) -> str:
    return ", ".join(f"'{v.value}'" for v in values)  # type: ignore[attr-defined]


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)  # external id; dedupe key
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=EventStatus.RECEIVED.value)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_duration_ms: Mapped[float | None] = mapped_column(Float)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("api_keys.id", ondelete="SET NULL"))

    __table_args__ = (
        CheckConstraint(f"status IN ({_in_list(EventStatus)})", name="status_valid"),
        # Purpose of each index (query pattern it serves):
        # - received_at: time-range analytics and "recent events" listing.
        Index("ix_events_received_at", "received_at"),
        # - status + received_at: recovery/sweeper scans and status-filtered lists.
        Index("ix_events_status_received_at", "status", "received_at"),
        # - event_type / source / customer + received_at: filtered lists and group-by analytics.
        Index("ix_events_event_type_received_at", "event_type", "received_at"),
        Index("ix_events_source_received_at", "source", "received_at"),
        Index("ix_events_customer_id_received_at", "customer_id", "received_at"),
        # - api_key_id + received_at: per-key daily quota counting.
        Index("ix_events_api_key_id_received_at", "api_key_id", "received_at"),
        # - partial: only RETRYING rows are scanned for due retries (tiny index).
        Index("ix_events_next_retry_at_retrying", "next_retry_at", postgresql_where=text("status = 'RETRYING'")),
    )


class AttemptOutcome(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ProcessingAttempt(Base):
    __tablename__ = "processing_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"outcome IN ({_in_list(AttemptOutcome)})", name="outcome_valid"),
        # unique(event_id, attempt_number) also serves "attempt history of one event" lookups.
        Index("uq_processing_attempts_event_id_attempt_number", "event_id", "attempt_number", unique=True),
    )


class DeadLetterStatus(str, enum.Enum):
    OPEN = "OPEN"
    REPROCESSED = "REPROCESSED"
    RESOLVED = "RESOLVED"


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dead_lettered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=DeadLetterStatus.OPEN.value)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    resolution_details: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"resolution_status IN ({_in_list(DeadLetterStatus)})", name="resolution_status_valid"),
        Index("ix_dead_letter_events_event_id", "event_id"),
        # Listing/filtering dead letters by resolution status, newest first.
        Index("ix_dead_letter_events_status_dead_lettered_at", "resolution_status", "dead_lettered_at"),
    )
