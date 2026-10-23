import time

import jwt
import pytest

from app.core import security
from app.core.exceptions import UnauthorizedError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.services.audit_service import sanitize
from app.services.processing_service import sanitize_error
from tests.helpers import make_settings

import uuid


def test_password_hash_is_argon2id_and_verifies():
    h = security.hash_password("Correct-Horse-9")
    assert h.startswith("$argon2id$")
    assert security.verify_password(h, "Correct-Horse-9")
    assert not security.verify_password(h, "wrong")
    assert not security.verify_password("not-a-hash", "x")
    assert security.hash_password("Correct-Horse-9") != h  # salted


def test_jwt_roundtrip_tamper_and_expiry():
    s = make_settings()
    uid = uuid.uuid4()
    token, jti, _ = security.create_access_token(uid, 0, s)
    claims = security.decode_access_token(token, s)
    assert claims["sub"] == str(uid) and claims["jti"] == jti
    with pytest.raises(UnauthorizedError):
        security.decode_access_token(token[:-2] + "xx", s)
    expired = jwt.encode({"sub": "x", "jti": "j", "iat": 1, "exp": int(time.time()) - 10, "iss": "streampulse"},
                         s.secret_key.get_secret_value(), algorithm="HS256")
    with pytest.raises(UnauthorizedError) as e:
        security.decode_access_token(expired, s)
    assert e.value.code == "TOKEN_EXPIRED"
    none_alg = jwt.encode({"sub": "x"}, key=None, algorithm="none")
    with pytest.raises(UnauthorizedError):
        security.decode_access_token(none_alg, s)  # alg=none rejected


def test_api_key_generation_and_hashing():
    s = make_settings()
    key, prefix = security.generate_api_key()
    assert key.startswith(f"sp_{prefix}_") and len(key) > 40
    assert security.parse_api_key_prefix(key) == prefix
    assert security.parse_api_key_prefix("garbage") is None
    stored = security.hash_api_key(key, s)
    assert key not in stored and len(stored) == 64
    assert security.verify_api_key(key, stored, s)
    assert not security.verify_api_key(key + "x", stored, s)
    assert security.generate_api_key()[0] != key


def test_rate_limiter_sliding_window():
    now = [0.0]
    rl = SlidingWindowRateLimiter(60, clock=lambda: now[0])
    assert all(rl.check("k", 3).allowed for _ in range(3))
    r = rl.check("k", 3)
    assert not r.allowed and r.retry_after >= 1
    assert rl.check("other", 3).allowed  # keys are independent
    now[0] = 61
    assert rl.check("k", 3).allowed  # window slid
    assert rl.cleanup() >= 0


def test_sanitizers_strip_secrets():
    assert sanitize({"password": "x", "nested": {"api_key": "y", "ok": 1}, "Authorization": "Bearer z"}) == {
        "password": "[REDACTED]", "nested": {"api_key": "[REDACTED]", "ok": 1}, "Authorization": "[REDACTED]"}
    msg = sanitize_error("fail Bearer abc.def.ghi token=hunter2 postgresql+asyncpg://u:p@h/db sp_0123abcd_" + "A" * 30)
    for secret in ("abc.def.ghi", "hunter2", "u:p@h", "A" * 30):
        assert secret not in msg
    assert len(sanitize_error("x" * 5000)) == 500
    assert "\n" not in sanitize_error("a\nb\nc")


def test_settings_reject_short_and_placeholder_secrets():
    from pydantic import ValidationError
    from tests.helpers import make_settings
    with pytest.raises(ValidationError, match="at least 32"):
        make_settings(secret_key="too-short")
    with pytest.raises(ValidationError, match="placeholder"):
        make_settings(app_env="production", secret_key="change_me_" + "x" * 30)
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
        make_settings(database_url="postgresql://u:p@localhost/db")
    ok = make_settings(app_env="production", secret_key="a-real-looking-secret-" + "k" * 20)
    assert ok.is_production
