from datetime import datetime

from pydantic import BaseModel


class TimeWindow(BaseModel):
    start: datetime
    end: datetime
    minutes: float


class OverviewResponse(BaseModel):
    window: TimeWindow
    total_received: int
    processed: int
    failed: int
    pending: int
    processing: int
    duplicate_submissions: int
    retries_total: int
    dead_letters_open: int
    events_per_minute: float
    success_rate: float | None  # processed / (processed + failed); None when nothing finished
    failure_rate: float | None
    avg_processing_latency_ms: float | None


class CountItem(BaseModel):
    key: str | None
    count: int


class EventsByTypeResponse(BaseModel):
    window: TimeWindow
    items: list[CountItem]


class TimeBucket(BaseModel):
    bucket: datetime
    count: int
    processed: int
    failed: int


class EventsOverTimeResponse(BaseModel):
    window: TimeWindow
    interval: str
    buckets: list[TimeBucket]


class FailureRateItem(BaseModel):
    key: str | None
    total: int
    processed: int
    failed: int
    failure_rate: float | None


class FailureRatesResponse(BaseModel):
    window: TimeWindow
    group_by: str
    items: list[FailureRateItem]


class LatencyStats(BaseModel):
    key: str | None = None
    samples: int
    avg_ms: float | None
    min_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    max_ms: float | None


class LatencyResponse(BaseModel):
    window: TimeWindow
    overall: LatencyStats
    groups: list[LatencyStats] = []


class TopSourcesResponse(BaseModel):
    window: TimeWindow
    items: list[CountItem]


class QueueStatusResponse(BaseModel):
    queue_size: int
    queue_capacity: int
    utilization: float
    workers_configured: int
    workers_alive: int
    running: bool
    saturated: bool
    db_counts: dict[str, int]


class DeadLetterItem(BaseModel):
    id: str
    event_pk: str
    event_id: str
    event_type: str
    source: str
    customer_id: str | None = None
    failure_reason: str
    retry_count: int
    dead_lettered_at: datetime
    resolution_status: str
    resolved_at: datetime | None = None
    resolution_details: str | None = None
