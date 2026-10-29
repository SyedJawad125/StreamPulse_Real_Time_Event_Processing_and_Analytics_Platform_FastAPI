# app/models/event.py
import enum

from sqlalchemy import (BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String,
                        Text, func, text)
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


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


def _in_list(values) -> str:
    return ", ".join(f"'{v.value}'" for v in values)


class Event(Base):
    __tablename__ = "events"

    id = Column(BigInteger, primary_key=True)
    event_id = Column(String(128), unique=True, nullable=False)  # producer-assigned; the de-duplication key
    event_type = Column(String(100), nullable=False)
    source = Column(String(100), nullable=False)
    customer_id = Column(String(100), nullable=True)
    schema_version = Column(String(20), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSONB, nullable=False)
    event_metadata = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String(20), nullable=False, server_default=EventStatus.RECEIVED.value)
    retry_count = Column(Integer, nullable=False, server_default="0")
    duplicate_count = Column(Integer, nullable=False, server_default="0")
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    processing_duration_ms = Column(Float, nullable=True)
    last_error = Column(Text, nullable=True)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        CheckConstraint(f"status IN ({_in_list(EventStatus)})", name="status_valid"),
        # Each index serves a concrete query pattern:
        Index("ix_events_received_at", "received_at"),                              # time ranges / recent events
        Index("ix_events_status_received_at", "status", "received_at"),             # sweeps + status-filtered lists
        Index("ix_events_event_type_received_at", "event_type", "received_at"),     # filtered lists / group-by
        Index("ix_events_source_received_at", "source", "received_at"),
        Index("ix_events_customer_id_received_at", "customer_id", "received_at"),
        Index("ix_events_api_key_id_received_at", "api_key_id", "received_at"),     # per-key daily quota
        Index("ix_events_next_retry_at_retrying", "next_retry_at", postgresql_where=text("status = 'RETRYING'")),
    )


class AttemptOutcome(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class ProcessingAttempt(Base):
    __tablename__ = "processing_attempts"

    id = Column(BigInteger, primary_key=True)
    event_id = Column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    outcome = Column(String(20), nullable=False)
    duration_ms = Column(Float, nullable=True)
    error = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(f"outcome IN ({_in_list(AttemptOutcome)})", name="outcome_valid"),
        Index("uq_processing_attempts_event_id_attempt_number", "event_id", "attempt_number", unique=True),
    )


class DeadLetterStatus(str, enum.Enum):
    OPEN = "OPEN"
    REPROCESSED = "REPROCESSED"
    RESOLVED = "RESOLVED"


class DeadLetterEvent(Base):
    __tablename__ = "dead_letter_events"

    id = Column(BigInteger, primary_key=True)
    event_id = Column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    failure_reason = Column(Text, nullable=False)
    retry_count = Column(Integer, nullable=False)
    dead_lettered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolution_status = Column(String(20), nullable=False, server_default=DeadLetterStatus.OPEN.value)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_details = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(f"resolution_status IN ({_in_list(DeadLetterStatus)})", name="resolution_status_valid"),
        Index("ix_dead_letter_events_event_id", "event_id"),
        Index("ix_dead_letter_events_status_dead_lettered_at", "resolution_status", "dead_lettered_at"),
    )
