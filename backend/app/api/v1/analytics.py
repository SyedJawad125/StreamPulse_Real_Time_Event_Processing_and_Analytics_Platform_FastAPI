from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ANALYTICS_READ
from app.dependencies import get_db, get_worker, require_permissions
from app.models.event import DeadLetterStatus, EventStatus
from app.schemas import analytics as s
from app.schemas.common import Page
from app.services import analytics_service as svc
from app.services.auth_service import CurrentUser
from app.workers.event_worker import EventWorkerManager

router = APIRouter(prefix="/analytics", tags=["Analytics"])
Auth = Depends(require_permissions(ANALYTICS_READ))


class Filters:
    """Shared query parameters. Time range applies to `received_at`; default is the last 24 hours."""

    def __init__(
        self,
        from_: datetime | None = Query(None, alias="from", description="Inclusive start (ISO-8601)"),
        to: datetime | None = Query(None, description="Exclusive end (ISO-8601)"),
        event_type: str | None = Query(None, max_length=100),
        source: str | None = Query(None, max_length=100),
        customer_id: str | None = Query(None, max_length=100),
    ) -> None:
        self.window = svc.resolve_window(from_, to)
        self.kw = {"event_type": event_type, "source": source, "customer_id": customer_id}


@router.get("/overview", response_model=s.OverviewResponse)
async def overview(f: Filters = Depends(), status: list[EventStatus] | None = Query(None),
                   _: CurrentUser = Auth, session: AsyncSession = Depends(get_db)):
    return await svc.overview(session, f.window, **f.kw, status=[x.value for x in status] if status else None)


@router.get("/events-by-type", response_model=s.EventsByTypeResponse)
async def events_by_type(f: Filters = Depends(), status: list[EventStatus] | None = Query(None),
                         limit: int = Query(50, ge=1, le=500), _: CurrentUser = Auth,
                         session: AsyncSession = Depends(get_db)):
    return await svc.events_by_type(session, f.window, limit, **f.kw, status=[x.value for x in status] if status else None)


@router.get("/events-over-time", response_model=s.EventsOverTimeResponse)
async def events_over_time(f: Filters = Depends(), interval: Literal["minute", "hour", "day"] = "hour",
                           status: list[EventStatus] | None = Query(None), _: CurrentUser = Auth,
                           session: AsyncSession = Depends(get_db)):
    return await svc.events_over_time(session, f.window, interval, **f.kw, status=[x.value for x in status] if status else None)


@router.get("/failure-rates", response_model=s.FailureRatesResponse)
async def failure_rates(f: Filters = Depends(), group_by: Literal["event_type", "source", "customer_id"] = "event_type",
                        limit: int = Query(50, ge=1, le=500), _: CurrentUser = Auth,
                        session: AsyncSession = Depends(get_db)):
    return await svc.failure_rates(session, f.window, group_by, limit, **f.kw)


@router.get("/processing-latency", response_model=s.LatencyResponse)
async def processing_latency(f: Filters = Depends(),
                             group_by: Literal["event_type", "source", "customer_id"] | None = None,
                             _: CurrentUser = Auth, session: AsyncSession = Depends(get_db)):
    return await svc.processing_latency(session, f.window, group_by, **f.kw)


@router.get("/top-sources", response_model=s.TopSourcesResponse)
async def top_sources(f: Filters = Depends(), limit: int = Query(10, ge=1, le=100),
                      status: list[EventStatus] | None = Query(None), _: CurrentUser = Auth,
                      session: AsyncSession = Depends(get_db)):
    return await svc.top_sources(session, f.window, limit, **f.kw, status=[x.value for x in status] if status else None)


@router.get("/queue-status", response_model=s.QueueStatusResponse)
async def queue_status(_: CurrentUser = Auth, session: AsyncSession = Depends(get_db),
                       manager: EventWorkerManager = Depends(get_worker)):
    st = manager.status()
    return s.QueueStatusResponse(
        queue_size=st["queue_size"], queue_capacity=st["queue_capacity"], utilization=st["utilization"],
        workers_configured=st["workers_configured"], workers_alive=st["workers_alive"], running=st["running"],
        saturated=st["saturated"], db_counts=await svc.status_counts(session))


@router.get("/dead-letters", response_model=Page[s.DeadLetterItem])
async def dead_letters(f: Filters = Depends(), resolution_status: DeadLetterStatus | None = None,
                       limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       _: CurrentUser = Auth, session: AsyncSession = Depends(get_db)):
    items, total = await svc.list_dead_letters(
        session, f.window, resolution_status=resolution_status.value if resolution_status else None,
        event_type=f.kw["event_type"], source=f.kw["source"], limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)
