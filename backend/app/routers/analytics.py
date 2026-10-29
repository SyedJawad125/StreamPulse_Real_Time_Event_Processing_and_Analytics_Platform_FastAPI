# app/routers/analytics.py
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app import database, schemas
from app.crud import analytics as svc
from app.dependencies.permission import require
from app.models import DeadLetterStatus, EventStatus

router = APIRouter(prefix="/api/analytics", tags=["Analytics"], dependencies=[require("read_analytics")])
GroupBy = Literal["event_type", "source", "customer_id"]


class Filters:
    """Shared query parameters. Time range applies to `received_at`; default is the last 24 hours."""

    def __init__(self, from_: datetime | None = Query(None, alias="from", description="Inclusive start (ISO-8601)"),
                 to: datetime | None = Query(None, description="Exclusive end (ISO-8601)"),
                 event_type: str | None = Query(None, max_length=100), source: str | None = Query(None, max_length=100),
                 customer_id: str | None = Query(None, max_length=100)) -> None:
        self.window = svc.resolve_window(from_, to)
        self.kw = {"event_type": event_type, "source": source, "customer_id": customer_id}


def _values(status: list[EventStatus] | None) -> list[str] | None:
    return [s.value for s in status] if status else None


@router.get("/v1/overview/", response_model=schemas.OverviewResponse)
def overview(f: Filters = Depends(), status: list[EventStatus] | None = Query(None),
             db: Session = Depends(database.get_db)):
    return svc.overview(db, f.window, **f.kw, status=_values(status))


@router.get("/v1/events-by-type/", response_model=schemas.EventsByTypeResponse)
def events_by_type(f: Filters = Depends(), status: list[EventStatus] | None = Query(None),
                   limit: int = Query(50, ge=1, le=500), db: Session = Depends(database.get_db)):
    return svc.events_by_type(db, f.window, limit, **f.kw, status=_values(status))


@router.get("/v1/events-over-time/", response_model=schemas.EventsOverTimeResponse)
def events_over_time(f: Filters = Depends(), interval: Literal["minute", "hour", "day"] = "hour",
                     status: list[EventStatus] | None = Query(None), db: Session = Depends(database.get_db)):
    return svc.events_over_time(db, f.window, interval, **f.kw, status=_values(status))


@router.get("/v1/failure-rates/", response_model=schemas.FailureRatesResponse)
def failure_rates(f: Filters = Depends(), group_by: GroupBy = "event_type", limit: int = Query(50, ge=1, le=500),
                  db: Session = Depends(database.get_db)):
    return svc.failure_rates(db, f.window, group_by, limit, **f.kw)


@router.get("/v1/processing-latency/", response_model=schemas.LatencyResponse)
def processing_latency(f: Filters = Depends(), group_by: GroupBy | None = None, db: Session = Depends(database.get_db)):
    return svc.processing_latency(db, f.window, group_by, **f.kw)


@router.get("/v1/top-sources/", response_model=schemas.TopSourcesResponse)
def top_sources(f: Filters = Depends(), limit: int = Query(10, ge=1, le=100),
                status: list[EventStatus] | None = Query(None), db: Session = Depends(database.get_db)):
    return svc.top_sources(db, f.window, limit, **f.kw, status=_values(status))


@router.get("/v1/queue-status/", response_model=schemas.QueueStatusResponse)
def queue_status(request: Request, db: Session = Depends(database.get_db)):
    st = request.app.state.worker_manager.status()
    return schemas.QueueStatusResponse(
        queue_size=st["queue_size"], queue_capacity=st["queue_capacity"], utilization=st["utilization"],
        workers_configured=st["workers_configured"], workers_alive=st["workers_alive"], running=st["running"],
        saturated=st["saturated"], db_counts=svc.status_counts(db))


@router.get("/v1/dead-letters/", response_model=schemas.DeadLetterListResponse)
def dead_letters(f: Filters = Depends(), resolution_status: DeadLetterStatus | None = None, skip: int = 0,
                 limit: int = Query(10, ge=1, le=200), db: Session = Depends(database.get_db)):
    items, total = svc.list_dead_letters(db, f.window, resolution_status=resolution_status.value if resolution_status else None,
                                         event_type=f.kw["event_type"], source=f.kw["source"], skip=skip, limit=limit)
    return {"status": "success", "result": {"count": total, "data": items}}
