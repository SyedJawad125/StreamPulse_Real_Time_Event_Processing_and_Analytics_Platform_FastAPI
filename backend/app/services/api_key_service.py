"""API-key lifecycle and authentication for event producers."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import NotFoundError, UnauthorizedError, UnprocessableError
from app.core.permissions import API_KEY_SCOPES
from app.core.security import generate_api_key, hash_api_key, parse_api_key_prefix, verify_api_key
from app.models.api_key import APIKey
from app.models.user import User
from app.schemas.api_key import APIKeyCreate, APIKeyUpdate
from app.services import audit_service

LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)  # avoids a DB write on every request


@dataclass(frozen=True)
class ApiKeyPrincipal:
    id: uuid.UUID
    name: str
    customer_id: str | None
    scopes: frozenset[str]
    rate_limit_per_minute: int
    daily_event_quota: int | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_api_key(
    session: AsyncSession, settings: Settings, request: Request, actor: User, data: APIKeyCreate
) -> tuple[APIKey, str]:
    bad = set(data.scopes) - API_KEY_SCOPES
    if bad:
        raise UnprocessableError(f"Unsupported scope(s): {', '.join(sorted(bad))}", code="INVALID_SCOPE")
    if not data.scopes:
        raise UnprocessableError("At least one scope is required", code="INVALID_SCOPE")
    if data.expires_at and data.expires_at <= _now():
        raise UnprocessableError("expires_at must be in the future", code="INVALID_EXPIRY")

    plaintext, prefix = generate_api_key()
    key = APIKey(
        name=data.name, description=data.description, key_prefix=prefix,
        key_hash=hash_api_key(plaintext, settings), owner_user_id=actor.id, customer_id=data.customer_id,
        scopes=sorted(set(data.scopes)), expires_at=data.expires_at,
        rate_limit_per_minute=data.rate_limit_per_minute or settings.default_rate_limit_per_minute,
        daily_event_quota=data.daily_event_quota,
    )
    session.add(key)
    await session.flush()  # assign the UUID so the audit row can reference it
    audit_service.record(session, action="api_key.created", actor=actor, request=request, target_type="api_key",
                         target_id=key.id, details={"name": key.name, "prefix": prefix, "customer_id": key.customer_id})
    await session.commit()
    return key, plaintext


async def list_api_keys(
    session: AsyncSession, *, is_active: bool | None, customer_id: str | None, limit: int, offset: int
) -> tuple[list[APIKey], int]:
    stmt = select(APIKey)
    if is_active is not None:
        stmt = stmt.where(APIKey.is_active == is_active)
    if customer_id:
        stmt = stmt.where(APIKey.customer_id == customer_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = (await session.scalars(stmt.order_by(APIKey.created_at.desc(), APIKey.id).limit(limit).offset(offset))).all()
    return list(items), total


async def get_api_key(session: AsyncSession, key_id: uuid.UUID) -> APIKey:
    key = await session.get(APIKey, key_id)
    if not key:
        raise NotFoundError("API key not found")
    return key


async def update_api_key(
    session: AsyncSession, request: Request, actor: User, key_id: uuid.UUID, data: APIKeyUpdate
) -> APIKey:
    key = await get_api_key(session, key_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("expires_at") and changes["expires_at"] <= _now():
        raise UnprocessableError("expires_at must be in the future", code="INVALID_EXPIRY")
    for k, v in changes.items():
        if k in ("name", "rate_limit_per_minute") and v is None:
            continue
        setattr(key, k, v)
    audit_service.record(session, action="api_key.updated", actor=actor, request=request, target_type="api_key",
                         target_id=key.id, details={"fields": sorted(changes)})
    await session.commit()
    return key


async def revoke_api_key(session: AsyncSession, request: Request, actor: User, key_id: uuid.UUID) -> APIKey:
    key = await get_api_key(session, key_id)
    if key.is_active:
        key.is_active = False
        key.revoked_at = _now()
        audit_service.record(session, action="api_key.revoked", actor=actor, request=request,
                             target_type="api_key", target_id=key.id, details={"name": key.name})
        await session.commit()
    return key


async def authenticate_api_key(session: AsyncSession, settings: Settings, raw: str | None) -> ApiKeyPrincipal:
    invalid = UnauthorizedError("Invalid or missing API key", code="INVALID_API_KEY",
                                headers={"WWW-Authenticate": "ApiKey"})
    if not raw:
        raise invalid
    prefix = parse_api_key_prefix(raw)
    if prefix is None:
        raise invalid
    key = await session.scalar(select(APIKey).where(APIKey.key_prefix == prefix))
    if key is None or not verify_api_key(raw, key.key_hash, settings):
        raise invalid
    now = _now()
    if not key.is_active or key.revoked_at is not None:
        raise UnauthorizedError("API key has been revoked", code="API_KEY_REVOKED",
                                headers={"WWW-Authenticate": "ApiKey"})
    if key.expires_at and key.expires_at <= now:
        raise UnauthorizedError("API key has expired", code="API_KEY_EXPIRED",
                                headers={"WWW-Authenticate": "ApiKey"})
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_WRITE_INTERVAL:
        await session.execute(update(APIKey).where(APIKey.id == key.id).values(last_used_at=now))
        await session.commit()
    return ApiKeyPrincipal(
        id=key.id, name=key.name, customer_id=key.customer_id, scopes=frozenset(key.scopes),
        rate_limit_per_minute=key.rate_limit_per_minute, daily_event_quota=key.daily_event_quota,
    )
