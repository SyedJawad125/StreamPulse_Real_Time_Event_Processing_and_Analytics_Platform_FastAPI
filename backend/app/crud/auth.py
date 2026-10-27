# app/crud/auth.py
"""Login with lockout/throttling, token refresh, logout and password change."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import models, oauth2, utils
from app.config import settings
from app.crud import audit
from app.exceptions import AppError
from app.rate_limit import SlidingWindowRateLimiter


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue_tokens(user: models.User) -> tuple[str, str]:
    data = {"user_id": user.id, "ver": user.token_version}
    return oauth2.create_access_token(data), oauth2.create_refresh_token(data)


def login(db: Session, request: Request, limiter: SlidingWindowRateLimiter, email: str, password: str) -> models.User:
    ip = request.client.host if request.client else "unknown"
    ip_res = limiter.check(f"login-ip:{ip}", settings.LOGIN_IP_LIMIT_PER_MINUTE)
    if not ip_res.allowed:
        raise AppError(429, "Too many login attempts from this address", "LOGIN_RATE_LIMITED",
                       {"Retry-After": str(ip_res.retry_after)})

    user = db.query(models.User).filter(func.lower(models.User.email) == email.lower(),
                                        models.User.deleted == False).first()  # noqa: E712
    now = _now()

    if user and user.locked_until and user.locked_until > now:
        audit.record(db, action="auth.login_blocked", actor=user, request=request, target_type="user",
                     target_id=user.id, success=False, details={"reason": "account_locked"})
        db.commit()
        raise AppError(429, "Account temporarily locked due to repeated failed logins", "ACCOUNT_LOCKED",
                       {"Retry-After": str(int((user.locked_until - now).total_seconds()) + 1)})

    if not utils.verify_password(password, user.hashed_password if user else None):
        details: dict = {"identifier_known": user is not None}
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                user.failed_login_attempts = 0
                details["locked"] = True
        audit.record(db, action="auth.login_failed", actor=user, request=request,
                     target_type="user" if user else None, target_id=user.id if user else None,
                     success=False, details=details)
        db.commit()
        # identical response for "no such user" and "wrong password"
        raise AppError(401, "Incorrect email or password", "INVALID_CREDENTIALS", {"WWW-Authenticate": "Bearer"})

    if not user.is_active:
        audit.record(db, action="auth.login_failed", actor=user, request=request, target_type="user",
                     target_id=user.id, success=False, details={"reason": "inactive"})
        db.commit()
        raise AppError(403, "Account is disabled", "ACCOUNT_DISABLED")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if utils.password_needs_rehash(user.hashed_password):
        user.hashed_password = utils.get_password_hash(password)
    audit.record(db, action="auth.login", actor=user, request=request, target_type="user", target_id=user.id)
    db.commit()
    limiter.reset(f"login-ip:{ip}")
    return user


def _revoke(db: Session, jti: str, user_id: int, expires_at: datetime) -> bool:
    """Insert into the denylist; False if it was already there."""
    result = db.execute(pg_insert(models.RevokedToken).values(jti=jti, user_id=user_id, expires_at=expires_at)
                        .on_conflict_do_nothing())
    return bool(result.rowcount)


def refresh(db: Session, request: Request, refresh_token: str) -> models.User:
    """Rotate: the presented refresh token is revoked and a new pair must be issued by the caller."""
    payload = oauth2.verify_refresh_token(refresh_token)
    user = db.query(models.User).filter(models.User.id == payload["user_id"],
                                        models.User.deleted == False).first()  # noqa: E712
    if user is None or not user.is_active or payload.get("ver", 0) != user.token_version:
        raise AppError(401, "Could not validate credentials", "INVALID_TOKEN", {"WWW-Authenticate": "Bearer"})
    expires = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    if not _revoke(db, payload["jti"], user.id, expires):  # atomic: a refresh token works exactly once
        db.rollback()
        raise AppError(401, "Token has been revoked", "TOKEN_REVOKED", {"WWW-Authenticate": "Bearer"})
    db.commit()
    return user


def logout(db: Session, request: Request, user: models.User, refresh_token: str | None = None) -> None:
    _revoke(db, user.token_jti, user.id, user.token_exp)
    if refresh_token:
        try:
            payload = oauth2.verify_refresh_token(refresh_token)
            if payload["user_id"] == user.id:
                _revoke(db, payload["jti"], user.id, datetime.fromtimestamp(payload["exp"], tz=timezone.utc))
        except AppError:
            pass  # an invalid/expired refresh token needs no revocation
    audit.record(db, action="auth.logout", actor=user, request=request, target_type="user", target_id=user.id)
    db.commit()


def change_password(db: Session, request: Request, user: models.User, current: str, new: str) -> models.User:
    if not utils.verify_password(current, user.hashed_password):
        audit.record(db, action="auth.password_change_failed", actor=user, request=request, target_type="user",
                     target_id=user.id, success=False)
        db.commit()
        raise AppError(401, "Current password is incorrect", "INVALID_CREDENTIALS")
    if new == current:
        raise AppError(422, "New password must differ from the current password", "PASSWORD_REUSED")
    user.hashed_password = utils.get_password_hash(new)
    user.token_version += 1  # invalidates every previously issued token
    audit.record(db, action="auth.password_changed", actor=user, request=request, target_type="user", target_id=user.id)
    db.commit()
    db.refresh(user)
    return user


def purge_expired_revocations(db: Session) -> int:
    result = db.execute(delete(models.RevokedToken).where(models.RevokedToken.expires_at < _now()))
    db.commit()
    return result.rowcount or 0
