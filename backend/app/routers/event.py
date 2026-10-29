# app/routers/event.py
"""Event ingestion (API-key auth), event queries (JWT + permissions), live stream and operator actions."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app import database, models, oauth2, schemas
from app.config import settings
from app.crud import event as crud
from app.crud import idempotency
from app.crud.api_key import ApiKeyPrincipal
from app.dependencies.api_key_auth import get_api_principal, idempotency_key_header
from app.dependencies.permission import has_permission, require
from app.exceptions import AppError
from app.models import EventStatus
from app.utils import sha256_hex
from app.workers.event_broker import sse_stream
from app.workers.event_worker import EventWorkerManager

router = APIRouter(prefix="/api/events", tags=["Events"])

_ERRORS = {
    401: {"description": "Missing, invalid, expired or revoked API key"},
    403: {"description": "Key lacks scope, or customer_id outside the key's tenant"},
    413: {"description": "Request body / payload / batch too large"},
    422: {"description": "Validation failed (schema, schema_version, timestamp, event-specific payload rules)"},
    429: {"description": "Rate limit or daily quota exceeded (see Retry-After)"},
    503: {"description": "Processing queue is saturated; retry later (see Retry-After)"},
}
_REJECTION_STATUS = {"payload_too_large": 413, "customer_mismatch": 403}


def _manager(request: Request) -> EventWorkerManager:
    return request.app.state.worker_manager


def _backpressure(manager: EventWorkerManager) -> None:
    if manager.queue.full():
        raise AppError(503, "Processing queue is full; retry shortly", "QUEUE_FULL", {"Retry-After": "1"})


def _idem_lookup(db: Session, principal: ApiKeyPrincipal, header_key: str | None, request: Request, body_repr):
    """Returns (key, request_hash, replay_response | None)."""
    if header_key is None:
        return None, None, None
    key = idempotency.validate_key(header_key)
    request_hash = sha256_hex(request.url.path + "\n" + json.dumps(body_repr, sort_keys=True, default=str))
    rec = idempotency.lookup(db, principal.id, key, request_hash)
    if rec:
        return key, request_hash, JSONResponse(rec.response_body, status_code=rec.response_status,
                                               headers={"Idempotent-Replayed": "true"})
    return key, request_hash, None


# ============================================================================= ingestion
@router.post("/v1/event/", status_code=202, response_model=schemas.EventAcceptedResponse,
             responses={200: {"description": "Duplicate event_id (already received)"}, **_ERRORS},
             summary="Ingest one event (API key). 202 = accepted for processing, NOT processed")
def ingest_event(body: schemas.EventIn, request: Request, response: Response,
                 principal: ApiKeyPrincipal = Depends(get_api_principal), db: Session = Depends(database.get_db),
                 idem: str | None = Depends(idempotency_key_header)):
    manager = _manager(request)
    key, req_hash, replay = _idem_lookup(db, principal, idem, request, body.model_dump(mode="json"))
    if replay:
        return replay

    rejection = crud.validate_semantics(body)
    if rejection:
        raise AppError(_REJECTION_STATUS.get(rejection.code, 422), rejection.message, rejection.code.upper())
    body, rejection = crud.tenant_check(body, principal)
    if rejection:
        raise AppError(403, rejection.message, rejection.code.upper())

    _backpressure(manager)
    crud.check_daily_quota(db, principal, 1)
    result = crud.insert_events(db, principal, [(0, body)])
    item = result.results[0]
    queued = manager.dispatch(result.new_ids)
    for e in result.new_events:
        manager.broker.publish("event.received", e)

    if item.status == "duplicate":
        response.status_code = 200
        payload = schemas.EventAcceptedResponse(status="duplicate", id=item.id, event_id=item.event_id)
    else:
        proc = EventStatus.QUEUED.value if item.id in queued else EventStatus.RECEIVED.value
        payload = schemas.EventAcceptedResponse(status="accepted", id=item.id, event_id=item.event_id,
                                                processing_status=proc)
    if key:
        idempotency.store(db, principal.id, key, req_hash, response.status_code or 202, jsonable_encoder(payload))
    return payload


@router.post("/v1/event/batch/", status_code=202, response_model=schemas.BatchIngestResponse, responses=_ERRORS,
             summary="Ingest a bounded batch. Per-event outcomes are returned; one bad event never rejects the rest")
def ingest_batch(body: schemas.BatchEventsRequest, request: Request, response: Response,
                 principal: ApiKeyPrincipal = Depends(get_api_principal), db: Session = Depends(database.get_db),
                 idem: str | None = Depends(idempotency_key_header)):
    manager = _manager(request)
    if len(body.events) > settings.MAX_BATCH_SIZE:
        raise AppError(413, f"Batch has {len(body.events)} events; the limit is {settings.MAX_BATCH_SIZE}",
                       "BATCH_TOO_LARGE")
    key, req_hash, replay = _idem_lookup(db, principal, idem, request, body.events)
    if replay:
        return replay

    results: dict[int, schemas.IngestItemResult] = {}
    valid: list[tuple[int, schemas.EventIn]] = []
    for index, raw in enumerate(body.events):
        parsed = crud.parse_and_validate(raw)
        if isinstance(parsed, crud.Rejection):
            event_id = raw.get("event_id") if isinstance(raw, dict) and isinstance(raw.get("event_id"), str) else None
            results[index] = schemas.IngestItemResult(index=index, event_id=event_id, status="rejected",
                                                      code=parsed.code, message=parsed.message)
            continue
        parsed, rej = crud.tenant_check(parsed, principal)
        if rej:
            results[index] = schemas.IngestItemResult(index=index, event_id=parsed.event_id, status="rejected",
                                                      code=rej.code, message=rej.message)
        else:
            valid.append((index, parsed))

    if valid:
        _backpressure(manager)
        crud.check_daily_quota(db, principal, len(valid))
        ingest = crud.insert_events(db, principal, valid)
        for r in ingest.results:
            results[r.index] = r
        manager.dispatch(ingest.new_ids)
        for e in ingest.new_events:
            manager.broker.publish("event.received", e)

    ordered = [results[i] for i in sorted(results)]
    payload = schemas.BatchIngestResponse(
        accepted=sum(r.status == "accepted" for r in ordered), duplicates=sum(r.status == "duplicate" for r in ordered),
        rejected=sum(r.status == "rejected" for r in ordered), results=ordered)
    if key:
        idempotency.store(db, principal.id, key, req_hash, 202, jsonable_encoder(payload))
    return payload


# ============================================================================= live stream (SSE)
@router.post("/v1/stream-ticket/", response_model=schemas.StreamTicketResponse,
             summary="One-time ticket for EventSource (which cannot send an Authorization header)")
def stream_ticket(request: Request, current_user: models.User = require("read_event")):
    ticket = request.app.state.ticket_store.issue(current_user.id, settings.STREAM_TICKET_TTL_SECONDS)
    return schemas.StreamTicketResponse(ticket=ticket, expires_in_seconds=settings.STREAM_TICKET_TTL_SECONDS)


def _authenticate_stream(request: Request, token: str | None, ticket: str | None) -> None:
    """Authenticate with a short-lived DB session that is released BEFORE streaming starts."""
    with database.SessionLocal() as db:
        if ticket:
            user_id = request.app.state.ticket_store.consume(ticket)
            if user_id is None:
                raise AppError(401, "Invalid or expired stream ticket", "INVALID_TICKET")
            user = db.query(models.User).filter(models.User.id == user_id, models.User.deleted == False).first()  # noqa: E712
            if user is None or not user.is_active:
                raise AppError(401, "Account is not active", "ACCOUNT_DISABLED")
            user.permissions_dict = {c: True for c in oauth2.effective_permission_codes(user)}
        else:
            user = oauth2.get_current_user(token, db)
        if not has_permission(user, "read_event"):
            raise AppError(403, "You do not have permission to perform this action", "PERMISSION_DENIED")


@router.get("/v1/stream/", response_class=StreamingResponse,
            summary="Server-Sent Events: live processing notifications (not a durable history)")
async def stream_events(request: Request, ticket: str | None = Query(None, max_length=100),
                        token: str | None = Depends(oauth2.oauth2_scheme)):
    await run_in_threadpool(_authenticate_stream, request, token, ticket)
    broker = request.app.state.broker
    sub = broker.subscribe()
    return StreamingResponse(
        sse_stream(broker, sub, request.is_disconnected, settings.SSE_HEARTBEAT_SECONDS),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ============================================================================= queries
@router.get("/v1/event/", response_model=schemas.EventListResponse, dependencies=[require("read_event")])
def list_events(status: list[EventStatus] | None = Query(None), event_type: str | None = Query(None, max_length=100),
                source: str | None = Query(None, max_length=100), customer_id: str | None = Query(None, max_length=100),
                event_id: str | None = Query(None, max_length=128, description="Exact external event_id"),
                from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                skip: int = 0, limit: int = Query(10, ge=1, le=200), db: Session = Depends(database.get_db)):
    items, total = crud.list_events(db, status=[s.value for s in status] if status else None, event_type=event_type,
                                    source=source, customer_id=customer_id, start=from_, end=to, event_id=event_id,
                                    skip=skip, limit=limit)
    return {"status": "success",
            "result": {"count": total, "data": [schemas.EventSummary.model_validate(e) for e in items]}}


@router.get("/v1/event/{id}", response_model=schemas.EventDetail, summary="Event with attempt and dead-letter history")
def get_event(id: int, db: Session = Depends(database.get_db), current_user: models.User = require("read_event")):
    event, attempts, dead = crud.get_event_with_history(db, id)
    can_see = has_permission(current_user, "read_event_payload")
    return schemas.EventDetail(
        **schemas.EventSummary.model_validate(event).model_dump(),
        payload=event.payload if can_see else None, metadata=event.event_metadata if can_see else None,
        payload_redacted=not can_see, next_retry_at=event.next_retry_at,
        attempts=[schemas.ProcessingAttemptOut.model_validate(a) for a in attempts],
        dead_letters=[schemas.DeadLetterOut.model_validate(d) for d in dead])


@router.post("/v1/event/{id}/reprocess", response_model=schemas.ReprocessResponse, status_code=202,
             summary="Re-queue a FAILED / DEAD_LETTER event")
def reprocess(id: int, request: Request, db: Session = Depends(database.get_db),
              current_user: models.User = require("reprocess_event")):
    manager = _manager(request)
    event = crud.reprocess_event(db, request, current_user, id)
    queued = manager.dispatch([event.id])
    manager.broker.publish("event.reprocess_requested", {"id": event.id, "event_id": event.event_id,
                                                         "event_type": event.event_type, "source": event.source,
                                                         "status": EventStatus.RECEIVED.value})
    status = EventStatus.QUEUED.value if event.id in queued else EventStatus.RECEIVED.value
    return schemas.ReprocessResponse(id=event.id, event_id=event.event_id, status=status, queued=event.id in queued)


@router.post("/v1/dead-letter/{id}/resolve", response_model=schemas.DeadLetterOut,
             summary="Mark a dead letter as resolved without reprocessing (e.g. discarded)")
def resolve_dead_letter(id: int, body: schemas.DeadLetterResolveRequest, request: Request,
                        db: Session = Depends(database.get_db), current_user: models.User = require("reprocess_event")):
    return crud.resolve_dead_letter(db, request, current_user, id, body.details)
