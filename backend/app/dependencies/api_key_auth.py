# app/dependencies/api_key_auth.py
"""Event-producer authentication: valid key -> scope check -> per-key rate limit."""
from fastapi import Depends, Header, Request, Response
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app import database
from app.crud import api_key as api_key_crud
from app.crud.api_key import ApiKeyPrincipal
from app.exceptions import AppError
from app.seed import INGEST_SCOPE

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_principal(request: Request, response: Response, raw_key: str | None = Depends(api_key_header),
                      db: Session = Depends(database.get_db)) -> ApiKeyPrincipal:
    principal = api_key_crud.authenticate_api_key(db, raw_key)
    if INGEST_SCOPE not in principal.scopes:
        raise AppError(403, f"API key lacks the '{INGEST_SCOPE}' scope", "INSUFFICIENT_SCOPE")
    result = request.app.state.rate_limiter.check(f"apikey:{principal.id}", principal.rate_limit_per_minute)
    if not result.allowed:
        raise AppError(429, "Rate limit exceeded", "RATE_LIMITED",
                       {"Retry-After": str(result.retry_after), "X-RateLimit-Limit": str(result.limit),
                        "X-RateLimit-Remaining": "0"})
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    return principal


def idempotency_key_header(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str | None:
    return idempotency_key
