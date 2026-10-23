"""Application errors and centralized, consistent error responses.

Every error body has the shape:
    {"error": {"code": "...", "message": "...", "request_id": "...", "details": ...}}
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code.replace("_", " ").capitalize()
        if code:
            self.code = code
        self.details = details
        self.headers = headers or {}


class NotFoundError(AppError):
    status_code, code = 404, "NOT_FOUND"


class ConflictError(AppError):
    status_code, code = 409, "CONFLICT"


class UnauthorizedError(AppError):
    status_code, code = 401, "UNAUTHORIZED"

    def __init__(self, message: str | None = None, **kw: Any) -> None:
        kw.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message or "Authentication required", **kw)


class ForbiddenError(AppError):
    status_code, code = 403, "FORBIDDEN"


class UnprocessableError(AppError):
    status_code, code = 422, "UNPROCESSABLE"


class PayloadTooLargeError(AppError):
    status_code, code = 413, "PAYLOAD_TOO_LARGE"


class RateLimitedError(AppError):
    status_code, code = 429, "RATE_LIMITED"


class ServiceUnavailableError(AppError):
    status_code, code = 503, "SERVICE_UNAVAILABLE"


def error_body(code: str, message: str, request_id: str | None, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details is not None:
        body["details"] = details
    return {"error": body}


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _headers(request: Request, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(extra or {})
    if rid := _rid(request):
        headers["X-Request-ID"] = rid
    return headers


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, _rid(request), exc.details),
            status_code=exc.status_code,
            headers=_headers(request, exc.headers),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            error_body(code, str(exc.detail), _rid(request)),
            status_code=exc.status_code,
            headers=_headers(request, dict(exc.headers or {})),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Drop `input`/`ctx` so submitted values (e.g. passwords) are never echoed back.
        details = [
            {"loc": list(e.get("loc", [])), "message": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            error_body("VALIDATION_ERROR", "Request validation failed", _rid(request), details),
            status_code=422,
            headers=_headers(request),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            error_body("INTERNAL_ERROR", "An unexpected error occurred", _rid(request)),
            status_code=500,
            headers=_headers(request),
        )
