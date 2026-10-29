# app/schemas/analytics.py
from datetime import datetime
from typing import Dict, List, Optional

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
    success_rate: Optional[float]  # processed / (processed + failed); None when nothing finished
    failure_rate: Optional[float]
    avg_processing_latency_ms: Optional[float]


class CountItem(BaseModel):
    key: Optional[str]
    count: int


class EventsByTypeResponse(BaseModel):
    window: TimeWindow
    items: List[CountItem]


class TimeBucket(BaseModel):
    bucket: datetime
    count: int
    processed: int
    failed: int


class EventsOverTimeResponse(BaseModel):
    window: TimeWindow
    interval: str
    buckets: List[TimeBucket]


class FailureRateItem(BaseModel):
    key: Optional[str]
    total: int
    processed: int
    failed: int
    failure_rate: Optional[float]


class FailureRatesResponse(BaseModel):
    window: TimeWindow
    group_by: str
    items: List[FailureRateItem]


class LatencyStats(BaseModel):
    key: Optional[str] = None
    samples: int
    avg_ms: Optional[float]
    min_ms: Optional[float]
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    p99_ms: Optional[float]
    max_ms: Optional[float]


class LatencyResponse(BaseModel):
    window: TimeWindow
    overall: LatencyStats
    groups: List[LatencyStats] = []


class TopSourcesResponse(BaseModel):
    window: TimeWindow
    items: List[CountItem]


class QueueStatusResponse(BaseModel):
    queue_size: int
    queue_capacity: int
    utilization: float
    workers_configured: int
    workers_alive: int
    running: bool
    saturated: bool
    db_counts: Dict[str, int]


class DeadLetterItem(BaseModel):
    id: int
    event_pk: int
    event_id: str
    event_type: str
    source: str
    customer_id: Optional[str] = None
    failure_reason: str
    retry_count: int
    dead_lettered_at: datetime
    resolution_status: str
    resolved_at: Optional[datetime] = None
    resolution_details: Optional[str] = None


class PaginatedDeadLetters(BaseModel):
    count: int
    data: List[DeadLetterItem]


class DeadLetterListResponse(BaseModel):
    status: str
    result: PaginatedDeadLetters
