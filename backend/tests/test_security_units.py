import time
import uuid

import jwt
import pytest
from pydantic import ValidationError

from app import oauth2, utils
from app.config import Settings, settings
from app.crud.audit import sanitize
from app.crud.processing import sanitize_error
from app.exceptions import AppError
from app.rate_limit import SlidingWindowRateLimiter


def test_password_hash_is_argon2id_and_verifies():
    h = utils.get_password_hash("Correct-Horse-9")
    assert h.startswith("$argon2id$")
    assert utils.verify_password("Correct-Horse-9", h)
    assert not utils.verify_password("wrong", h)
    assert not utils.verify_password("x", None)            # unknown user: always False (dummy hash burns equal time)
    assert not utils.verify_password("x", "not-a-hash")
    assert utils.get_password_hash("Correct-Horse-9") != h  # salted


def test_password_strength_rules():
    with pytest.raises(ValueError):
        utils.validate_password_strength("short1")
    with pytest.raises(ValueError):
        utils.validate_password_strength("onlyletterspassword")
    assert utils.validate_password_strength("GoodPassw0rd")


def test_jwt_roundtrip_tamper_expiry_and_type():
    token = oauth2.create_access_token({"user_id": 7, "ver": 0})
    claims = oauth2.decode_token(token, "access")
    assert claims["user_id"] == 7 and claims["type"] == "access" and claims["jti"]
    with pytest.raises(AppError) as e:
        oauth2.decode_token(token, "refresh")                 # an access token is not a refresh token
    assert e.value.code == "INVALID_TOKEN_TYPE"
    with pytest.raises(AppError):
        oauth2.decode_token(token[:-2] + "xx", "access")
    expired = jwt.encode({"user_id": 1, "type": "access", "jti": "j", "iat": 1, "exp": int(time.time()) - 10,
                          "iss": settings.JWT_ISSUER}, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(AppError) as e:
        oauth2.decode_token(expired, "access")
    assert e.value.code == "TOKEN_EXPIRED"
    with pytest.raises(AppError):
        oauth2.decode_token(jwt.encode({"user_id": 1}, key=None, algorithm="none"), "access")  # alg=none rejected


def test_api_key_generation_and_hashing():
    key, prefix = utils.generate_api_key()
    assert key.startswith(f"sp_{prefix}_") and len(key) > 40 and utils.parse_api_key_prefix(key) == prefix
    assert utils.parse_api_key_prefix("garbage") is None
    stored = utils.hash_api_key(key)
    assert key not in stored and len(stored) == 64
    assert utils.verify_api_key(key, stored) and not utils.verify_api_key(key + "x", stored)
    assert utils.generate_api_key()[0] != key


def test_rate_limiter_sliding_window():
    now = [0.0]
    rl = SlidingWindowRateLimiter(60, clock=lambda: now[0])
    assert all(rl.check("k", 3).allowed for _ in range(3))
    r = rl.check("k", 3)
    assert not r.allowed and r.retry_after >= 1
    assert rl.check("other", 3).allowed
    now[0] = 61
    assert rl.check("k", 3).allowed
    assert rl.cleanup() >= 0


def test_rate_limiter_is_thread_safe():
    from concurrent.futures import ThreadPoolExecutor
    rl = SlidingWindowRateLimiter(60)
    with ThreadPoolExecutor(16) as pool:
        results = list(pool.map(lambda _: rl.check("k", 50).allowed, range(400)))
    assert sum(results) == 50  # exactly the limit, never more, under concurrency


def test_sanitizers_strip_secrets():
    assert sanitize({"password": "x", "nested": {"api_key": "y", "ok": 1}, "Authorization": "Bearer z"}) == {
        "password": "[REDACTED]", "nested": {"api_key": "[REDACTED]", "ok": 1}, "Authorization": "[REDACTED]"}
    msg = sanitize_error("fail Bearer abc.def.ghi token=hunter2 postgresql+psycopg2://u:p@h/db sp_0123abcd_" + "A" * 30)
    for secret in ("abc.def.ghi", "hunter2", "u:p@h", "A" * 30):
        assert secret not in msg
    assert len(sanitize_error("x" * 5000)) == 500 and "\n" not in sanitize_error("a\nb\nc")


def test_settings_reject_bad_values():
    base = dict(_env_file=None)
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(**base, SECRET_KEY="too-short")
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(**base, APP_ENV="production", SECRET_KEY="change_me_" + "x" * 30)
    with pytest.raises(ValidationError, match="synchronous"):
        Settings(**base, DATABASE_URL="postgresql+asyncpg://u:p@localhost/db")
    ok = Settings(**base, DATABASE_URL="postgresql://u:p@localhost/db", APP_ENV="production",
                  SECRET_KEY="a-real-looking-secret-" + "k" * 20)
    assert ok.IS_PRODUCTION and ok.DATABASE_URL.startswith("postgresql+psycopg2://")


def test_filter_helpers_escape_wildcards(client, admin_headers):
    # a literal "%" in a search term must not behave like a wildcard
    r = client.get("/api/roles/v1/role/", params={"name": "%"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["result"]["count"] == 0
