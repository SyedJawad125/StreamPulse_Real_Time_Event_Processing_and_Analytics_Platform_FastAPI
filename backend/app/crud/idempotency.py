# app/crud/idempotency.py
"""HTTP request idempotency via the `Idempotency-Key` header.

Distinct from event-level de-duplication (unique `event_id`):
  Idempotency-Key -> "this exact HTTP request was already handled; replay the stored response"
  event_id        -> "this logical event already exists" (DB unique constraint)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.exceptions import AppError
from app.models import IdempotencyRecord

_KEY_RE = re.compile(r"^[\x21-\x7e]{1,128}$")


def validate_key(key: str) -> str:
    if not _KEY_RE.match(key):
        raise AppError(422, "Idempotency-Key must be 1-128 printable ASCII characters", "INVALID_IDEMPOTENCY_KEY")
    return key


def lookup(db: Session, api_key_id: int, key: str, request_hash: str) -> IdempotencyRecord | None:
    rec = db.query(IdempotencyRecord).filter(IdempotencyRecord.api_key_id == api_key_id,
                                             IdempotencyRecord.key == key).first()
    if rec is None:
        return None
    if rec.request_hash != request_hash:
        raise AppError(409, "Idempotency-Key was already used with a different request body", "IDEMPOTENCY_KEY_REUSED")
    return rec


def store(db: Session, api_key_id: int, key: str, request_hash: str, status: int, body: dict) -> None:
    db.execute(pg_insert(IdempotencyRecord)
               .values(api_key_id=api_key_id, key=key, request_hash=request_hash, response_status=status,
                       response_body=body)
               .on_conflict_do_nothing(constraint="uq_idempotency_records_api_key_id_key"))
    db.commit()


def purge_expired(db: Session, ttl_hours: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    result = db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.created_at < cutoff))
    db.commit()
    return result.rowcount or 0
