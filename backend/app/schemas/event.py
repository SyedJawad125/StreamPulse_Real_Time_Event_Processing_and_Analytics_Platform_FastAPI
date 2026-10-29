# app/schemas/event.py
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EVENT_ID_PATTERN = r"^[A-Za-z0-9._:\-]+$"
EVENT_TYPE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$"
SOURCE_PATTERN = r"^[A-Za-z0-9._\-]+$"


class EventIn(BaseModel):
    """Event as submitted by a producer application."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128, pattern=EVENT_ID_PATTERN,
                          description="Producer-assigned unique id; used for de-duplication")
    event_type: str = Field(min_length=1, max_length=100, pattern=EVENT_TYPE_PATTERN, examples=["order.created"])
    source: str = Field(min_length=1, max_length=100, pattern=SOURCE_PATTERN, examples=["checkout-service"])
    customer_id: Optional[str] = Field(default=None, min_length=1, max_length=100, pattern=SOURCE_PATTERN)
    schema_version: str = Field(default="1.0", max_length=20)
    timestamp: AwareDatetime = Field(description="When the event occurred (timezone-aware ISO-8601)")
    payload: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchEventsRequest(BaseModel):
    # Items are validated one by one so a single bad event never rejects the whole batch.
    events: List[Any] = Field(min_length=1)


class IngestItemResult(BaseModel):
    index: int
    event_id: Optional[str] = None
    status: Literal["accepted", "duplicate", "rejected"]
    id: Optional[int] = None
    code: Optional[str] = None
    message: Optional[str] = None


class EventAcceptedResponse(BaseModel):
    """Returned when an event is accepted. NOTE: accepted != processed."""
    status: Literal["accepted", "duplicate"]
    id: int
    event_id: str
    processing_status: Optional[str] = Field(
        default=None, description="Pipeline state at acceptance time (RECEIVED or QUEUED) - never PROCESSED")


class BatchIngestResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    results: List[IngestItemResult]


class ProcessingAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    attempt_number: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    outcome: str
    duration_ms: Optional[float] = None
    error: Optional[str] = None


class DeadLetterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: int
    failure_reason: str
    retry_count: int
    dead_lettered_at: datetime
    resolution_status: str
    resolved_at: Optional[datetime] = None
    resolved_by_user_id: Optional[int] = None
    resolution_details: Optional[str] = None


class EventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: str
    event_type: str
    source: str
    customer_id: Optional[str] = None
    schema_version: str
    occurred_at: datetime
    status: str
    retry_count: int
    duplicate_count: int
    received_at: datetime
    processing_started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    processing_duration_ms: Optional[float] = None
    last_error: Optional[str] = None


class EventDetail(EventSummary):
    payload: Optional[dict[str, Any]] = None  # None when redacted for the caller
    metadata: Optional[dict[str, Any]] = None
    payload_redacted: bool = False
    next_retry_at: Optional[datetime] = None
    attempts: List[ProcessingAttemptOut] = []
    dead_letters: List[DeadLetterOut] = []


class PaginatedEvents(BaseModel):
    count: int
    data: List[EventSummary]


class EventListResponse(BaseModel):
    status: str
    result: PaginatedEvents


class ReprocessResponse(BaseModel):
    id: int
    event_id: str
    status: str
    queued: bool


class DeadLetterResolveRequest(BaseModel):
    details: Optional[str] = Field(default=None, max_length=1000)
