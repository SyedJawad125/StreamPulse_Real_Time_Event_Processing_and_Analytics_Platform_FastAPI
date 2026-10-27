# app/crud/audit.py
"""Audit logging. Secrets are stripped from `details` before persisting."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditLog, User

_SENSITIVE = re.compile(r"password|passwd|token|secret|api_?key|authorization|key_hash|^key$|cookie|ticket", re.I)


def sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SENSITIVE.search(str(k)) else sanitize(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, depth + 1) for v in value[:50]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


def record(db: Session, *, action: str, actor: Optional[User] = None, request: Optional[Request] = None,
           target_type: str | None = None, target_id: object | None = None, details: dict | None = None,
           success: bool = True) -> AuditLog:
    """Stage an audit row in the caller's transaction (the caller commits)."""
    entry = AuditLog(
        action=action,
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        success=success,
        ip_address=(request.client.host if request is not None and request.client else None),
        request_id=(getattr(request.state, "request_id", None) if request is not None else None),
        details=sanitize(details or {}),
    )
    db.add(entry)
    return entry


def list_logs(db: Session, *, action: str | None, actor_user_id: int | None, success: bool | None,
              start: datetime | None, end: datetime | None, skip: int, limit: int) -> tuple[list[AuditLog], int]:
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if actor_user_id:
        q = q.filter(AuditLog.actor_user_id == actor_user_id)
    if success is not None:
        q = q.filter(AuditLog.success == success)
    if start:
        q = q.filter(AuditLog.created_at >= start)
    if end:
        q = q.filter(AuditLog.created_at < end)
    total = q.with_entities(func.count(AuditLog.id)).scalar() or 0
    rows = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(skip).limit(limit).all()
    return rows, total
