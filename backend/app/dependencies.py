"""FastAPI dependencies: settings, DB session, authentication and permission checks."""
from __future__ import annotations

from typing import AsyncIterator, Callable

from fastapi import Depends, Header, Request, Response
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import ForbiddenError, RateLimitedError, UnauthorizedError
from app.core.permissions import EVENTS_INGEST
from app.core.rate_limit import SlidingWindowRateLimiter
from app.services import api_key_service, auth_service
from app.services.api_key_service import ApiKeyPrincipal
from app.services.auth_service import CurrentUser
from app.workers.event_worker import EventWorkerManager

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_worker(request: Request) -> EventWorkerManager:
    return request.app.state.worker_manager


def get_limiter(request: Request) -> SlidingWindowRateLimiter:
    return request.app.state.rate_limiter


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services commit explicitly; un-committed work is rolled back on close."""
    async with request.app.state.session_factory() as session:
        yield session


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> CurrentUser:
    if not token:
        raise UnauthorizedError("Not authenticated", code="NOT_AUTHENTICATED")
    return await auth_service.authenticate_token(session, settings, token)


def require_permissions(*codes: str) -> Callable[..., CurrentUser]:
    """Dependency factory: caller must hold ALL of `codes` (enforced server-side)."""

    async def checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = [c for c in codes if c not in current.permissions]
        if missing:
            raise ForbiddenError("You do not have permission to perform this action", code="PERMISSION_DENIED",
                                 details={"required": list(codes)})
        return current

    return checker


def require_any_permission(*codes: str) -> Callable[..., CurrentUser]:
    async def checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(c in current.permissions for c in codes):
            raise ForbiddenError("You do not have permission to perform this action", code="PERMISSION_DENIED",
                                 details={"required_any": list(codes)})
        return current

    return checker


async def get_api_principal(
    response: Response,
    raw_key: str | None = Depends(api_key_header),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    limiter: SlidingWindowRateLimiter = Depends(get_limiter),
) -> ApiKeyPrincipal:
    """Authenticate an event producer: valid key -> scope check -> per-key rate limit."""
    principal = await api_key_service.authenticate_api_key(session, settings, raw_key)
    if EVENTS_INGEST not in principal.scopes:
        raise ForbiddenError("API key lacks the 'events.ingest' scope", code="INSUFFICIENT_SCOPE")
    result = limiter.check(f"apikey:{principal.id}", principal.rate_limit_per_minute)
    if not result.allowed:
        raise RateLimitedError("Rate limit exceeded", code="RATE_LIMITED", headers={
            "Retry-After": str(result.retry_after), "X-RateLimit-Limit": str(result.limit), "X-RateLimit-Remaining": "0"})
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    return principal


def idempotency_key_header(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str | None:
    return idempotency_key
