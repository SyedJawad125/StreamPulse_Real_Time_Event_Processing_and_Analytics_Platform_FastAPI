"""Password hashing (Argon2id), JWT access tokens and API-key helpers."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import Settings
from app.core.exceptions import UnauthorizedError

# argon2-cffi's PasswordHasher defaults to Argon2id.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash("streampulse-timing-equalizer")


# Hashing is CPU/memory heavy: run it in a worker thread so the event loop is never blocked.
async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str | None, password: str) -> bool:
    """Verify; when no hash exists, burn equivalent time to avoid user-enumeration timing leaks."""
    if password_hash is None:
        await asyncio.to_thread(verify_password, _dummy_hash(), password)
        return False
    return await asyncio.to_thread(verify_password, password_hash, password)


# --- JWT -------------------------------------------------------------------
def create_access_token(user_id: uuid.UUID, token_version: int, settings: Settings) -> tuple[str, str, datetime]:
    """Return (token, jti, expires_at)."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.access_token_expire_minutes)
    jti = uuid.uuid4().hex
    claims = {
        "sub": str(user_id),
        "jti": jti,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": settings.jwt_issuer,
    }
    token = jwt.encode(claims, settings.secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, jti, expires


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "jti", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Access token has expired", code="TOKEN_EXPIRED") from None
    except jwt.PyJWTError:
        raise UnauthorizedError("Invalid access token", code="INVALID_TOKEN") from None
    return claims


# --- API keys --------------------------------------------------------------
API_KEY_RE = re.compile(r"^sp_([0-9a-f]{8})_([A-Za-z0-9_\-]{20,})$")


def generate_api_key() -> tuple[str, str]:
    """Return (plaintext_key, prefix). Plaintext is shown to the user exactly once."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)  # 256 bits of entropy
    return f"sp_{prefix}_{secret}", prefix


def parse_api_key_prefix(raw: str) -> str | None:
    m = API_KEY_RE.match(raw)
    return m.group(1) if m else None


def hash_api_key(raw: str, settings: Settings) -> str:
    """HMAC-SHA256 with a server-side pepper. API keys are high-entropy, so a fast keyed hash is appropriate."""
    return hmac.new(
        settings.api_key_pepper.get_secret_value().encode(), raw.encode(), hashlib.sha256
    ).hexdigest()


def verify_api_key(raw: str, stored_hash: str, settings: Settings) -> bool:
    return hmac.compare_digest(hash_api_key(raw, settings), stored_hash)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()
