# app/logging_config.py
"""Structured (JSON) logging with request-id correlation."""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from app.config import Settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname, "logger": record.name, "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key != "request_id":
                data[key] = value
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    formatter: logging.Formatter = JsonFormatter() if settings.LOG_JSON else logging.Formatter(
        "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.APP_ENV != "testing":
        settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(settings.LOGS_DIR / "streampulse.log", maxBytes=5_000_000,
                                            backupCount=3, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(formatter)
        h.addFilter(RequestIdFilter())
        root.addHandler(h)
    logging.getLogger("uvicorn.access").disabled = True  # our middleware writes the access log
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if settings.DB_ECHO else logging.WARNING)
