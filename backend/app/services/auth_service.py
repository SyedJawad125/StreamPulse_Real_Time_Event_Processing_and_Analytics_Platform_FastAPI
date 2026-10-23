"""Authentication: login with lockout/throttling, token validation, logout, password change."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import ForbiddenError, RateLimitedError, UnauthorizedError, UnprocessableError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password_async,
    password_needs_rehash,
    verify_password_async,
)
from app.models.auth_support import RevokedToken
from app.models.user import User
from app.services import audit_service

logger = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    user: User
    permissions: frozenset[str]
    jti: str
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def login(
    session: AsyncSession,
    settings: Settings,
    limiter: SlidingWindowRateLimiter,
    request: Request,
    identifier: str,
    password: str,
) -> tuple[str, datetime, User]:
    ip = request.client.host if request.client else "unknown"
    ip_result = limiter.check(f"login-ip:{ip}", settings.login_ip_limit_per_minute)
    if not ip_result.allowed:
        raise RateLimitedError(
            "Too many login attempts from this address", code="LOGIN_RATE_LIMITED",
            headers={"Retry-After": str(ip_result.retry_after)},
        )

    ident = identifier.strip().lower()
    user = await session.scalar(select(User).where(or_(User.username == ident, User.email == ident)))
    now = _now()

    if user and user.locked_until and user.locked_until > now:
        retry = int((user.locked_until - now).total_seconds()) + 1
        audit_service.record(session, action="auth.login_blocked", actor=user, request=request, target_type="user",
                             target_id=user.id, success=False, details={"reason": "account_locked"})
        await session.commit()
        raise RateLimitedError("Account temporarily locked due to repeated failed logins",
                               code="ACCOUNT_LOCKED", headers={"Retry-After": str(retry)})

    ok = await verify_password_async(user.password_hash if user else None, password)
    if not ok or user is None:
        details: dict = {"identifier_known": user is not None}
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_max_failed_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_attempts = 0
                details["locked"] = True
        audit_service.record(session, action="auth.login_failed", actor=user, request=request,
                             target_type="user" if user else None, target_id=user.id if user else None,
                             success=False, details=details)
        await session.commit()
        raise UnauthorizedError("Invalid username or password", code="INVALID_CREDENTIALS")

    if not user.is_active:
        audit_service.record(session, action="auth.login_failed", actor=user, request=request, target_type="user",
                             target_id=user.id, success=False, details={"reason": "inactive"})
        await session.commit()
        raise ForbiddenError("This account has been deactivated", code="ACCOUNT_DISABLED")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if password_needs_rehash(user.password_hash):
        user.password_hash = await hash_password_async(password)
    token, _jti, expires = create_access_token(user.id, user.token_version, settings)
    audit_service.record(session, action="auth.login", actor=user, request=request, target_type="user", target_id=user.id)
    await session.commit()
    limiter.reset(f"login-ip:{ip}")
    return token, expires, user


async def authenticate_token(session: AsyncSession, settings: Settings, token: str) -> CurrentUser:
    claims = decode_access_token(token, settings)
    jti = claims["jti"]
    if await session.scalar(select(RevokedToken.jti).where(RevokedToken.jti == jti)):
        raise UnauthorizedError("Token has been revoked", code="TOKEN_REVOKED")
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError:
        raise UnauthorizedError("Invalid access token", code="INVALID_TOKEN") from None
    user = await session.get(User, user_id)
    if user is None or claims.get("ver") != user.token_version:
        raise UnauthorizedError("Invalid access token", code="INVALID_TOKEN")
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated", code="ACCOUNT_DISABLED")
    return CurrentUser(
        user=user,
        permissions=user.permission_codes,
        jti=jti,
        expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
    )


async def logout(session: AsyncSession, request: Request, current: CurrentUser) -> None:
    await session.execute(
        pg_insert(RevokedToken)
        .values(jti=current.jti, user_id=current.user.id, expires_at=current.expires_at)
        .on_conflict_do_nothing()
    )
    audit_service.record(session, action="auth.logout", actor=current.user, request=request,
                         target_type="user", target_id=current.user.id)
    await session.commit()


async def change_password(
    session: AsyncSession, settings: Settings, request: Request, user: User, current_password: str, new_password: str
) -> tuple[str, datetime]:
    if not await verify_password_async(user.password_hash, current_password):
        audit_service.record(session, action="auth.password_change_failed", actor=user, request=request,
                             target_type="user", target_id=user.id, success=False)
        await session.commit()
        raise UnauthorizedError("Current password is incorrect", code="INVALID_CREDENTIALS")
    if new_password == current_password:
        raise UnprocessableError("New password must differ from the current password", code="PASSWORD_REUSED")
    if user.username in new_password.lower():
        raise UnprocessableError("Password must not contain the username", code="PASSWORD_WEAK")
    user.password_hash = await hash_password_async(new_password)
    user.token_version += 1  # invalidates every previously issued token
    token, _jti, expires = create_access_token(user.id, user.token_version, settings)
    audit_service.record(session, action="auth.password_changed", actor=user, request=request,
                         target_type="user", target_id=user.id)
    await session.commit()
    return token, expires


async def purge_expired_revocations(session: AsyncSession) -> int:
    result = await session.execute(delete(RevokedToken).where(RevokedToken.expires_at < _now()))
    await session.commit()
    return result.rowcount or 0
