# app/crud/api_key.py
"""API-key lifecycle and authentication for event producers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app import models, utils
from app.config import settings
from app.crud import audit
from app.exceptions import AppError
from app.schemas.api_key import APIKeyCreate, APIKeyUpdate
from app.seed import INGEST_SCOPE

ALLOWED_SCOPES = frozenset({INGEST_SCOPE})
LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)  # avoids a DB write on every request


@dataclass(frozen=True)
class ApiKeyPrincipal:
    id: int
    name: str
    customer_id: str | None
    scopes: frozenset[str]
    rate_limit_per_minute: int
    daily_event_quota: int | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_api_key(db: Session, request: Request, actor: models.User, data: APIKeyCreate) -> tuple[models.APIKey, str]:
    bad = set(data.scopes) - ALLOWED_SCOPES
    if bad or not data.scopes:
        raise AppError(422, f"Unsupported scope(s): {', '.join(sorted(bad)) or '(none given)'}", "INVALID_SCOPE")
    if data.expires_at and data.expires_at <= _now():
        raise AppError(422, "expires_at must be in the future", "INVALID_EXPIRY")
    plaintext, prefix = utils.generate_api_key()
    key = models.APIKey(
        name=data.name, description=data.description, key_prefix=prefix, key_hash=utils.hash_api_key(plaintext),
        customer_id=data.customer_id, scopes=sorted(set(data.scopes)), expires_at=data.expires_at,
        rate_limit_per_minute=data.rate_limit_per_minute or settings.DEFAULT_RATE_LIMIT_PER_MINUTE,
        daily_event_quota=data.daily_event_quota, created_by_user_id=actor.id,
    )
    db.add(key)
    db.flush()  # assign the id so the audit row can reference it
    audit.record(db, action="api_key.created", actor=actor, request=request, target_type="api_key", target_id=key.id,
                 details={"name": key.name, "prefix": prefix, "customer_id": key.customer_id})
    db.commit()
    db.refresh(key)
    return key, plaintext


def list_api_keys(db: Session, *, is_active: bool | None, customer_id: str | None, include_deleted: bool,
                  skip: int, limit: int) -> tuple[list[models.APIKey], int]:
    q = models.APIKey.get_all_including_deleted(db) if include_deleted else models.APIKey.get_active(db)
    if is_active is not None:
        q = q.filter(models.APIKey.is_active == is_active)
    if customer_id:
        q = q.filter(models.APIKey.customer_id == customer_id)
    total = q.count()
    return q.order_by(models.APIKey.created_at.desc(), models.APIKey.id.desc()).offset(skip).limit(limit).all(), total


def get_api_key(db: Session, key_id: int) -> models.APIKey:
    key = db.query(models.APIKey).filter(models.APIKey.id == key_id, models.APIKey.deleted == False).first()  # noqa: E712
    if not key:
        raise AppError(404, f"API key with id {key_id} not found")
    return key


def update_api_key(db: Session, request: Request, actor: models.User, key_id: int, data: APIKeyUpdate) -> models.APIKey:
    key = get_api_key(db, key_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("expires_at") and changes["expires_at"] <= _now():
        raise AppError(422, "expires_at must be in the future", "INVALID_EXPIRY")
    for k, v in changes.items():
        if k in ("name", "rate_limit_per_minute") and v is None:
            continue
        setattr(key, k, v)
    key.updated_by_user_id = actor.id
    audit.record(db, action="api_key.updated", actor=actor, request=request, target_type="api_key", target_id=key.id,
                 details={"fields": sorted(changes)})
    db.commit()
    db.refresh(key)
    return key


def revoke_api_key(db: Session, request: Request, actor: models.User, key_id: int) -> models.APIKey:
    key = get_api_key(db, key_id)
    if key.is_active:
        key.is_active = False
        key.revoked_at = _now()
        key.updated_by_user_id = actor.id
        audit.record(db, action="api_key.revoked", actor=actor, request=request, target_type="api_key",
                     target_id=key.id, details={"name": key.name})
        db.commit()
        db.refresh(key)
    return key


def delete_api_key(db: Session, request: Request, actor: models.User, key_id: int) -> None:
    """Soft delete (also revokes): the key can never authenticate again."""
    key = get_api_key(db, key_id)
    key.is_active = False
    key.revoked_at = key.revoked_at or _now()
    key.soft_delete(user_id=actor.id)
    audit.record(db, action="api_key.deleted", actor=actor, request=request, target_type="api_key", target_id=key.id,
                 details={"name": key.name})
    db.commit()


def authenticate_api_key(db: Session, raw: str | None) -> ApiKeyPrincipal:
    invalid = AppError(401, "Invalid or missing API key", "INVALID_API_KEY", {"WWW-Authenticate": "ApiKey"})
    if not raw:
        raise invalid
    prefix = utils.parse_api_key_prefix(raw)
    if prefix is None:
        raise invalid
    key = db.query(models.APIKey).filter(models.APIKey.key_prefix == prefix).first()
    if key is None or not utils.verify_api_key(raw, key.key_hash):
        raise invalid
    now = _now()
    if key.deleted or not key.is_active or key.revoked_at is not None:
        raise AppError(401, "API key has been revoked", "API_KEY_REVOKED", {"WWW-Authenticate": "ApiKey"})
    if key.expires_at and key.expires_at <= now:
        raise AppError(401, "API key has expired", "API_KEY_EXPIRED", {"WWW-Authenticate": "ApiKey"})
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_WRITE_INTERVAL:
        db.execute(update(models.APIKey).where(models.APIKey.id == key.id).values(last_used_at=now))
        db.commit()
    return ApiKeyPrincipal(id=key.id, name=key.name, customer_id=key.customer_id, scopes=frozenset(key.scopes),
                           rate_limit_per_minute=key.rate_limit_per_minute, daily_event_quota=key.daily_event_quota)
