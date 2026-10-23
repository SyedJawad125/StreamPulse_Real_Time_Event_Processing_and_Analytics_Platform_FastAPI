from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EVENT_ID_PATTERN = r"^[A-Za-z0-9._:\-]+$"
EVENT_TYPE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$"
SOURCE_PATTERN = r"^[A-Za-z0-9._\-]+$"


class EventIn(BaseModel):
    """Event as submitted by a producer application."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128, pattern=EVENT_ID_PATTERN,
                          description="Producer-assigned unique id; used for deduplication")
    event_type: str = Field(min_length=1, max_length=100, pattern=EVENT_TYPE_PATTERN, examples=["order.created"])
    source: str = Field(min_length=1, max_length=100, pattern=SOURCE_PATTERN, examples=["checkout-service"])
    customer_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=SOURCE_PATTERN)
    schema_version: str = Field(default="1.0", max_length=20)
    timestamp: AwareDatetime = Field(description="When the event occurred (timezone-aware ISO-8601)")
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchEventsRequest(BaseModel):
    # Items are validated one by one in the service so one bad event doesn't reject the whole batch.
    events: list[Any] = Field(min_length=1)


class IngestItemResult(BaseModel):
    index: int
    event_id: str | None = None
    status: Literal["accepted", "duplicate", "rejected"]
    id: uuid.UUID | None = None
    code: str | None = None
    message: str | None = None


class EventAcceptedResponse(BaseModel):
    """Returned when an event is accepted. NOTE: accepted != processed."""

    status: Literal["accepted", "duplicate"]
    id: uuid.UUID
    event_id: str
    processing_status: str | None = Field(
        default=None, description="Pipeline state at acceptance time (RECEIVED or QUEUED), never PROCESSED"
    )


class BatchIngestResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    results: list[IngestItemResult]


class ProcessingAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    attempt_number: int
    started_at: datetime
    completed_at: datetime | None = None
    outcome: str
    duration_ms: float | None = None
    error: str | None = None


class EventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: str
    event_type: str
    source: str
    customer_id: str | None = None
    schema_version: str
    occurred_at: datetime
    status: str
    retry_count: int
    duplicate_count: int
    received_at: datetime
    processing_started_at: datetime | None = None
    completed_at: datetime | None = None
    processing_duration_ms: float | None = None
    last_error: str | None = None


class DeadLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    failure_reason: str
    retry_count: int
    dead_lettered_at: datetime
    resolution_status: str
    resolved_at: datetime | None = None
    resolved_by_user_id: uuid.UUID | None = None
    resolution_details: str | None = None


class EventDetail(EventSummary):
    payload: dict[str, Any] | None = None  # None when redacted for the caller
    metadata: dict[str, Any] | None = None
    payload_redacted: bool = False
    next_retry_at: datetime | None = None
    attempts: list[ProcessingAttemptOut] = []
    dead_letters: list[DeadLetterOut] = []


class ReprocessResponse(BaseModel):
    id: uuid.UUID
    event_id: str
    status: str
    queued: bool


class DeadLetterResolveRequest(BaseModel):
    details: str | None = Field(default=None, max_length=1000)
