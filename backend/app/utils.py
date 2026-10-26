# app/utils.py
"""Password hashing (Argon2id), API-key helpers, pagination and query-filter helpers."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import or_

from app.config import settings

# argon2-cffi's PasswordHasher uses Argon2id by default.
_hasher = PasswordHasher()


def get_password_hash(password: str) -> str:
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Constant-effort check: when no hash exists a dummy hash is verified, so unknown users cost the same time."""
    try:
        return _hasher.verify(hashed_password or _dummy_hash(), plain_password) and hashed_password is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(hashed_password: str) -> bool:
    return _hasher.check_needs_rehash(hashed_password)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash("streampulse-timing-equalizer")


def validate_password_strength(password: str) -> str:
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one digit")
    return password


# ---------------- API keys ----------------
_API_KEY_RE = re.compile(r"^sp_([0-9a-f]{8})_([A-Za-z0-9_\-]{20,})$")


def generate_api_key() -> tuple[str, str]:
    """(plaintext, prefix). The plaintext (256 bits of entropy) is shown to the user exactly once."""
    prefix = secrets.token_hex(4)
    return f"sp_{prefix}_{secrets.token_urlsafe(32)}", prefix


def parse_api_key_prefix(raw: str) -> str | None:
    m = _API_KEY_RE.match(raw)
    return m.group(1) if m else None


def hash_api_key(raw: str) -> str:
    """HMAC-SHA256 keyed with a server-side pepper (API keys are high-entropy, so a fast keyed hash is right)."""
    return hmac.new(settings.API_KEY_PEPPER.encode(), raw.encode(), hashlib.sha256).hexdigest()


def verify_api_key(raw: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(raw), stored_hash)


def sha256_hex(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


# ---------------- pagination / filters ----------------
def paginate_data(query, skip: int = 0, limit: int = 10) -> dict:
    """Return {"count": total, "data": [...]} for a SQLAlchemy Query."""
    return {"count": query.count(), "data": query.offset(skip).limit(limit).all()}


def _like(column, value: str):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


def _apply(query, params, model, fields: tuple[str, ...]):
    for field in fields:
        if value := params.get(field):
            query = query.filter(_like(getattr(model, field), value))
    if search := params.get("search"):
        query = query.filter(or_(*[_like(getattr(model, f), search) for f in fields]))
    return query


def filter_roles(params, query):
    from app.models import Role
    return _apply(query, params, Role, ("name", "code", "description"))


def filter_permissions(params, query):
    from app.models import Permission
    return _apply(query, params, Permission, ("name", "code", "module_name", "description"))


def filter_users(params, query):
    from app.models import User
    query = _apply(query, params, User, ("username", "email"))
    if (role_id := params.get("role_id")) and role_id.isdigit():
        query = query.filter(User.role_id == int(role_id))
    return query
