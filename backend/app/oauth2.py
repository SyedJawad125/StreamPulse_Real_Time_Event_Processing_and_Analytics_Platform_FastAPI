# app/oauth2.py
"""JWT creation/validation and the `get_current_user` dependency (same public API as before)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from . import database, models
from .config import settings
from .exceptions import AppError

# `tokenUrl` powers the Swagger "Authorize" button (form-based login endpoint).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/user/v1/token/", auto_error=False)

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS


def _create_token(data: dict, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        **data,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "iss": settings.JWT_ISSUER,
    }
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(data: dict) -> str:
    return _create_token(data, "access", timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(data: dict) -> str:
    return _create_token(data, "refresh", timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], issuer=settings.JWT_ISSUER,
                             options={"require": ["exp", "iat", "jti", "iss"]})
    except jwt.ExpiredSignatureError:
        raise AppError(401, "Token has expired", "TOKEN_EXPIRED", {"WWW-Authenticate": "Bearer"}) from None
    except jwt.PyJWTError:
        raise AppError(401, "Could not validate credentials", "INVALID_TOKEN", {"WWW-Authenticate": "Bearer"}) from None
    if payload.get("type") != expected_type:
        raise AppError(401, f"Invalid token type (expected {expected_type})", "INVALID_TOKEN_TYPE",
                       {"WWW-Authenticate": "Bearer"})
    if not isinstance(payload.get("user_id"), int):
        raise AppError(401, "Could not validate credentials", "INVALID_TOKEN", {"WWW-Authenticate": "Bearer"})
    return payload


def verify_refresh_token(refresh_token: str) -> dict:
    return decode_token(refresh_token, "refresh")


# ------------------------------------------------------------------ permissions
def effective_permission_codes(user: models.User) -> set[str]:
    """Role permissions + permissions granted directly to the user (soft-deleted ones never count)."""
    codes: set[str] = set()
    if user.role and not user.role.deleted:
        codes |= {p.code for p in user.role.permissions if not p.deleted}
    codes |= {p.code for p in user.permissions if not p.deleted}
    return codes


def build_permissions_dict(db: Session, user: models.User) -> dict[str, bool]:
    """{permission_code: bool} for EVERY permission (the shape the frontend expects). Superusers get all True."""
    all_codes = [c for (c,) in db.query(models.Permission.code).filter(models.Permission.deleted == False).all()]  # noqa: E712
    granted = set(all_codes) if user.is_superuser else effective_permission_codes(user)
    result = {code: (code in granted) for code in all_codes}
    # a directly granted code that is not in the catalogue is still reported
    result.update({code: True for code in granted if code not in result})
    return result


# ------------------------------------------------------------------ dependency
def get_current_user(token: str | None = Depends(oauth2_scheme), db: Session = Depends(database.get_db)) -> models.User:
    if not token:
        raise AppError(401, "Not authenticated", "NOT_AUTHENTICATED", {"WWW-Authenticate": "Bearer"})
    payload = decode_token(token, "access")

    if db.query(models.RevokedToken.jti).filter(models.RevokedToken.jti == payload["jti"]).first():
        raise AppError(401, "Token has been revoked", "TOKEN_REVOKED", {"WWW-Authenticate": "Bearer"})

    user = db.query(models.User).filter(models.User.id == payload["user_id"], models.User.deleted == False).first()  # noqa: E712
    if user is None or payload.get("ver", 0) != user.token_version:
        raise AppError(401, "Could not validate credentials", "INVALID_TOKEN", {"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise AppError(401, "Account is disabled", "ACCOUNT_DISABLED", {"WWW-Authenticate": "Bearer"})

    # Attached for permission checks (see app/dependencies/permission.py)
    user.permissions_dict = {code: True for code in effective_permission_codes(user)}
    user.token_jti = payload["jti"]
    user.token_exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    return user
