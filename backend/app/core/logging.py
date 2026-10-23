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
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        for key, value in record.__dict__.items():  # structured "extra" fields
            if key not in _RESERVED and key != "request_id":
                data[key] = value
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter: logging.Formatter = (
        JsonFormatter()
        if settings.log_json
        else logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    )
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.app_env != "testing":
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                settings.logs_dir / "streampulse.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
        )
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RequestIdFilter())
        root.addHandler(handler)

    # Our middleware writes the access log; silence uvicorn's duplicate.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if settings.db_echo else logging.WARNING)
