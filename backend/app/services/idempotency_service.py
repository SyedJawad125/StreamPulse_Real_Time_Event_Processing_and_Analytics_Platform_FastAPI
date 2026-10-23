"""HTTP request idempotency via the `Idempotency-Key` header.

Distinct from event-level deduplication (unique `event_id`):
  * Idempotency-Key  -> "this exact HTTP request was already handled; replay the stored response".
  * event_id         -> "this logical event already exists", enforced by a DB unique constraint.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnprocessableError
from app.models.auth_support import IdempotencyRecord

_KEY_RE = re.compile(r"^[\x21-\x7e]{1,128}$")


def validate_key(key: str) -> str:
    if not _KEY_RE.match(key):
        raise UnprocessableError("Idempotency-Key must be 1-128 printable ASCII characters", code="INVALID_IDEMPOTENCY_KEY")
    return key


async def lookup(session: AsyncSession, api_key_id: uuid.UUID, key: str, request_hash: str) -> IdempotencyRecord | None:
    rec = await session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.api_key_id == api_key_id, IdempotencyRecord.key == key)
    )
    if rec is None:
        return None
    if rec.request_hash != request_hash:
        raise ConflictError("Idempotency-Key was already used with a different request body", code="IDEMPOTENCY_KEY_REUSED")
    return rec


async def store(
    session: AsyncSession, api_key_id: uuid.UUID, key: str, request_hash: str, status: int, body: dict
) -> None:
    await session.execute(
        pg_insert(IdempotencyRecord)
        .values(api_key_id=api_key_id, key=key, request_hash=request_hash, response_status=status, response_body=body)
        .on_conflict_do_nothing(constraint="uq_idempotency_records_api_key_id_key")
    )
    await session.commit()


async def purge_expired(session: AsyncSession, ttl_hours: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    result = await session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.created_at < cutoff))
    await session.commit()
    return result.rowcount or 0
