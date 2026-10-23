"""Audit logging. Secrets are stripped from details before persisting."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User

_SENSITIVE = re.compile(r"password|passwd|token|secret|api_?key|authorization|key_hash|^key$|cookie|ticket", re.I)


def sanitize(value: Any, depth: int = 0) -> Any:
    """Recursively redact values whose key looks secret-bearing."""
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SENSITIVE.search(str(k)) else sanitize(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, depth + 1) for v in value[:50]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


def record(
    session: AsyncSession,
    *,
    action: str,
    actor: User | None = None,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    details: dict[str, Any] | None = None,
    success: bool = True,
) -> AuditLog:
    """Stage an audit row in the caller's transaction (caller commits)."""
    entry = AuditLog(
        action=action,
        actor_user_id=actor.id if actor else None,
        actor_username=actor.username if actor else None,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        success=success,
        ip_address=(request.client.host if request and request.client else None),
        request_id=(getattr(request.state, "request_id", None) if request else None),
        details=sanitize(details or {}),
    )
    session.add(entry)
    return entry


async def list_logs(
    session: AsyncSession, *, action: str | None, actor_user_id: uuid.UUID | None, success: bool | None,
    start: datetime | None, end: datetime | None, limit: int, offset: int,
) -> tuple[list[AuditLog], int]:
    conds = []
    if action:
        conds.append(AuditLog.action == action)
    if actor_user_id:
        conds.append(AuditLog.actor_user_id == actor_user_id)
    if success is not None:
        conds.append(AuditLog.success == success)
    if start:
        conds.append(AuditLog.created_at >= start)
    if end:
        conds.append(AuditLog.created_at < end)
    total = await session.scalar(select(func.count(AuditLog.id)).where(*conds)) or 0
    rows = (await session.scalars(
        select(AuditLog).where(*conds).order_by(AuditLog.created_at.desc(), AuditLog.id).limit(limit).offset(offset)
    )).all()
    return list(rows), total
