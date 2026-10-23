"""Event ingestion (API-key auth), event queries (JWT + permissions), live stream and reprocessing."""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import (
    AppError,
    ForbiddenError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnauthorizedError,
    UnprocessableError,
)
from app.core.permissions import EVENTS_READ, EVENTS_READ_PAYLOAD, EVENTS_REPROCESS
from app.dependencies import (
    get_api_principal,
    get_current_user,
    get_db,
    get_settings_dep,
    get_worker,
    idempotency_key_header,
    oauth2_scheme,
    require_permissions,
)
from app.models.event import EventStatus
from app.models.user import User
from app.schemas.auth import StreamTicketResponse
from app.schemas.common import Page
from app.schemas.event import (
    BatchEventsRequest,
    BatchIngestResponse,
    DeadLetterOut,
    DeadLetterResolveRequest,
    EventAcceptedResponse,
    EventDetail,
    EventIn,
    EventSummary,
    IngestItemResult,
    ProcessingAttemptOut,
    ReprocessResponse,
)
from app.services import auth_service, event_service, idempotency_service
from app.services.api_key_service import ApiKeyPrincipal
from app.services.auth_service import CurrentUser
from app.services.event_broker import sse_stream
from app.workers.event_worker import EventWorkerManager

router = APIRouter(prefix="/events", tags=["Events"])

_ERRORS = {
    401: {"description": "Missing, invalid, expired or revoked API key"},
    403: {"description": "Key lacks scope, or customer_id outside the key's tenant"},
    413: {"description": "Request body / payload / batch too large"},
    422: {"description": "Validation failed (schema, schema_version, timestamp, event-specific payload rules)"},
    429: {"description": "Rate limit or daily quota exceeded (see Retry-After)"},
    503: {"description": "Processing queue is saturated; retry later (see Retry-After)"},
}

_REJECTION_STATUS = {"payload_too_large": 413, "customer_mismatch": 403}


def _backpressure(manager: EventWorkerManager) -> None:
    if manager.queue.full():
        raise ServiceUnavailableError("Processing queue is full; retry shortly", code="QUEUE_FULL",
                                      headers={"Retry-After": "1"})


def _replay(rec) -> JSONResponse:
    return JSONResponse(rec.response_body, status_code=rec.response_status, headers={"Idempotent-Replayed": "true"})


async def _idem_lookup(session, principal, header_key, request: Request):
    """Returns (key, request_hash, replay_response|None)."""
    if header_key is None:
        return None, None, None
    key = idempotency_service.validate_key(header_key)
    req_hash = hashlib.sha256(request.url.path.encode() + b"\n" + await request.body()).hexdigest()
    rec = await idempotency_service.lookup(session, principal.id, key, req_hash)
    return key, req_hash, (_replay(rec) if rec else None)


def _publish_received(manager: EventWorkerManager, events: list[dict]) -> None:
    for e in events:
        manager.broker.publish("event.received", e)


@router.post("", status_code=202, response_model=EventAcceptedResponse, responses={200: {"description": "Duplicate event_id (already received)"}, **_ERRORS},
             summary="Ingest one event (API key). 202 = accepted for processing, NOT processed")
async def ingest_event(
    body: EventIn, request: Request, response: Response,
    principal: ApiKeyPrincipal = Depends(get_api_principal), session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep), manager: EventWorkerManager = Depends(get_worker),
    idem: str | None = Depends(idempotency_key_header),
):
    key, req_hash, replay = await _idem_lookup(session, principal, idem, request)
    if replay:
        return replay

    ev = event_service.validate_semantics(body, settings)
    if ev:
        status = _REJECTION_STATUS.get(ev.code, 422)
        cls = PayloadTooLargeError if status == 413 else UnprocessableError
        raise cls(ev.message, code=ev.code.upper())
    body, rejection = event_service.tenant_check(body, principal)
    if rejection:
        raise ForbiddenError(rejection.message, code=rejection.code.upper())

    _backpressure(manager)
    await event_service.check_daily_quota(session, principal, 1)
    result = await event_service.insert_events(session, principal, [(0, body)])
    item = result.results[0]
    queued = await manager.dispatch(result.new_ids)
    _publish_received(manager, result.new_events)

    if item.status == "duplicate":
        response.status_code = 200
        payload = EventAcceptedResponse(status="duplicate", id=item.id, event_id=item.event_id, processing_status=None)
    else:
        proc = EventStatus.QUEUED.value if item.id in queued else EventStatus.RECEIVED.value
        payload = EventAcceptedResponse(status="accepted", id=item.id, event_id=item.event_id, processing_status=proc)
    if key:
        await idempotency_service.store(session, principal.id, key, req_hash, response.status_code or 202,
                                        jsonable_encoder(payload))
    return payload


@router.post("/batch", status_code=202, response_model=BatchIngestResponse, responses=_ERRORS,
             summary="Ingest a bounded batch. Per-event outcomes are returned; one bad event never rejects the others")
async def ingest_batch(
    body: BatchEventsRequest, request: Request, response: Response,
    principal: ApiKeyPrincipal = Depends(get_api_principal), session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep), manager: EventWorkerManager = Depends(get_worker),
    idem: str | None = Depends(idempotency_key_header),
):
    if len(body.events) > settings.max_batch_size:
        raise PayloadTooLargeError(f"Batch has {len(body.events)} events; the limit is {settings.max_batch_size}",
                                   code="BATCH_TOO_LARGE")
    key, req_hash, replay = await _idem_lookup(session, principal, idem, request)
    if replay:
        return replay

    rejected: dict[int, IngestItemResult] = {}
    valid: list[tuple[int, EventIn]] = []
    for index, raw in enumerate(body.events):
        parsed = event_service.parse_and_validate(raw, settings)
        if isinstance(parsed, event_service.Rejection):
            rejected[index] = IngestItemResult(
                index=index, event_id=raw.get("event_id") if isinstance(raw, dict) and isinstance(raw.get("event_id"), str) else None,
                status="rejected", code=parsed.code, message=parsed.message)
            continue
        parsed, rej = event_service.tenant_check(parsed, principal)
        if rej:
            rejected[index] = IngestItemResult(index=index, event_id=parsed.event_id, status="rejected",
                                               code=rej.code, message=rej.message)
        else:
            valid.append((index, parsed))

    results = dict(rejected)
    if valid:
        _backpressure(manager)
        await event_service.check_daily_quota(session, principal, len(valid))
        ingest = await event_service.insert_events(session, principal, valid)
        # insert_events returns results keyed by the *position within `valid`'s original indexes*
        for r in ingest.results:
            results[r.index] = r
        await manager.dispatch(ingest.new_ids)
        _publish_received(manager, ingest.new_events)

    ordered = [results[i] for i in sorted(results)]
    payload = BatchIngestResponse(
        accepted=sum(r.status == "accepted" for r in ordered), duplicates=sum(r.status == "duplicate" for r in ordered),
        rejected=sum(r.status == "rejected" for r in ordered), results=ordered)
    if key:
        await idempotency_service.store(session, principal.id, key, req_hash, 202, jsonable_encoder(payload))
    return payload


# --------------------------------------------------------------------------- live stream
@router.post("/stream-ticket", response_model=StreamTicketResponse,
             summary="Get a short-lived one-time ticket for EventSource (which cannot send an Authorization header)")
async def stream_ticket(request: Request, current: CurrentUser = Depends(require_permissions(EVENTS_READ)),
                        settings: Settings = Depends(get_settings_dep)) -> StreamTicketResponse:
    tickets: dict = request.app.state.stream_tickets
    now = time.monotonic()
    for t in [t for t, (_, exp) in tickets.items() if exp < now]:  # opportunistic cleanup
        del tickets[t]
    if len(tickets) > 10_000:
        raise ServiceUnavailableError("Too many outstanding tickets", code="TICKET_CAPACITY")
    ticket = secrets.token_urlsafe(32)
    tickets[ticket] = (current.user.id, now + settings.stream_ticket_ttl_seconds)
    return StreamTicketResponse(ticket=ticket, expires_in_seconds=settings.stream_ticket_ttl_seconds)


async def _stream_user(request: Request, token: str | None, ticket: str | None) -> User:
    """Authenticate the stream with a short-lived DB session that is released BEFORE streaming starts."""
    settings: Settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        if ticket:
            entry = request.app.state.stream_tickets.pop(ticket, None)  # one-time use
            if not entry or entry[1] < time.monotonic():
                raise UnauthorizedError("Invalid or expired stream ticket", code="INVALID_TICKET")
            user = await session.get(User, entry[0])
            if user is None or not user.is_active:
                raise UnauthorizedError("Account is not active", code="ACCOUNT_DISABLED")
            perms = user.permission_codes
        elif token:
            current = await auth_service.authenticate_token(session, settings, token)
            user, perms = current.user, current.permissions
        else:
            raise UnauthorizedError("Not authenticated", code="NOT_AUTHENTICATED")
    if EVENTS_READ not in perms:
        raise ForbiddenError("You do not have permission to perform this action", code="PERMISSION_DENIED")
    return user


@router.get("/stream", summary="Server-Sent Events: live processing notifications (not a durable history)",
            response_class=StreamingResponse)
async def stream_events(request: Request, ticket: str | None = Query(None, max_length=100),
                        token: str | None = Depends(oauth2_scheme)) -> StreamingResponse:
    await _stream_user(request, token, ticket)
    settings: Settings = request.app.state.settings
    broker = request.app.state.broker
    sub = broker.subscribe()
    return StreamingResponse(
        sse_stream(broker, sub, request.is_disconnected, settings.sse_heartbeat_seconds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# --------------------------------------------------------------------------- queries
@router.get("", response_model=Page[EventSummary], summary="List events (newest first)")
async def list_events(
    status: list[EventStatus] | None = Query(None), event_type: str | None = Query(None, max_length=100),
    source: str | None = Query(None, max_length=100), customer_id: str | None = Query(None, max_length=100),
    event_id: str | None = Query(None, max_length=128, description="Exact external event_id"),
    from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    _: CurrentUser = Depends(require_permissions(EVENTS_READ)), session: AsyncSession = Depends(get_db),
) -> Page[EventSummary]:
    items, total = await event_service.list_events(
        session, status=[s.value for s in status] if status else None, event_type=event_type, source=source,
        customer_id=customer_id, start=from_, end=to, event_id=event_id, limit=limit, offset=offset)
    return Page(items=[EventSummary.model_validate(e) for e in items], total=total, limit=limit, offset=offset)


@router.get("/{event_pk}", response_model=EventDetail, summary="Event detail with attempts and dead-letter history")
async def get_event(event_pk: uuid.UUID, current: CurrentUser = Depends(require_permissions(EVENTS_READ)),
                    session: AsyncSession = Depends(get_db)) -> EventDetail:
    event, attempts, dead = await event_service.get_event_with_history(session, event_pk)
    can_see = EVENTS_READ_PAYLOAD in current.permissions
    return EventDetail(
        **EventSummary.model_validate(event).model_dump(),
        payload=event.payload if can_see else None,
        metadata=event.event_metadata if can_see else None,
        payload_redacted=not can_see,
        next_retry_at=event.next_retry_at,
        attempts=[ProcessingAttemptOut.model_validate(a) for a in attempts],
        dead_letters=[DeadLetterOut.model_validate(d) for d in dead],
    )


@router.post("/{event_pk}/reprocess", response_model=ReprocessResponse, status_code=202,
             summary="Re-queue a FAILED / DEAD_LETTER event")
async def reprocess(event_pk: uuid.UUID, request: Request,
                    current: CurrentUser = Depends(require_permissions(EVENTS_REPROCESS)),
                    session: AsyncSession = Depends(get_db),
                    manager: EventWorkerManager = Depends(get_worker)) -> ReprocessResponse:
    event = await event_service.reprocess_event(session, request, current.user, event_pk)
    queued = await manager.dispatch([event.id])
    manager.broker.publish("event.reprocess_requested", {"id": str(event.id), "event_id": event.event_id,
                                                         "event_type": event.event_type, "source": event.source,
                                                         "status": EventStatus.RECEIVED.value})
    status = EventStatus.QUEUED.value if event.id in queued else EventStatus.RECEIVED.value
    return ReprocessResponse(id=event.id, event_id=event.event_id, status=status, queued=event.id in queued)


@router.post("/dead-letters/{dead_letter_id}/resolve", response_model=DeadLetterOut,
             summary="Mark a dead letter as resolved without reprocessing (e.g. discarded)")
async def resolve_dead_letter(dead_letter_id: uuid.UUID, body: DeadLetterResolveRequest, request: Request,
                              current: CurrentUser = Depends(require_permissions(EVENTS_REPROCESS)),
                              session: AsyncSession = Depends(get_db)) -> DeadLetterOut:
    dl = await event_service.resolve_dead_letter(session, request, current.user, dead_letter_id, body.details)
    return DeadLetterOut.model_validate(dl)
