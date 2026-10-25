# app/exceptions.py
"""Uniform error responses.

Shape (a superset of FastAPI's default {"detail": ...} so existing frontends keep working):
    {"detail": "<message>", "code": "<MACHINE_CODE>", "request_id": "<id>"}
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_DEFAULT_CODES = {
    400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 422: "UNPROCESSABLE", 429: "RATE_LIMITED", 503: "SERVICE_UNAVAILABLE",
}


class AppError(HTTPException):
    """HTTPException carrying a stable machine-readable `code`."""

    def __init__(self, status_code: int, detail: str, code: str | None = None, headers: dict[str, str] | None = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code or _DEFAULT_CODES.get(status_code, "HTTP_ERROR")


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _response(request: Request, status: int, detail, code: str, headers: dict | None = None) -> JSONResponse:
    headers = dict(headers or {})
    if rid := _rid(request):
        headers["X-Request-ID"] = rid
    return JSONResponse({"detail": detail, "code": code, "request_id": _rid(request)}, status_code=status, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = getattr(exc, "code", None) or _DEFAULT_CODES.get(exc.status_code, "HTTP_ERROR")
        return _response(request, exc.status_code, exc.detail, code, dict(exc.headers or {}))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # `input`/`ctx` are dropped so submitted values (e.g. passwords) are never echoed back.
        detail = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return _response(request, 422, detail, "VALIDATION_ERROR")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _response(request, 500, "An unexpected error occurred", "INTERNAL_ERROR")
