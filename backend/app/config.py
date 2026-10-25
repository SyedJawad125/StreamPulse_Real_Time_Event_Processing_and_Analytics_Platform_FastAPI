# app/config.py
"""Application settings (environment variables / .env). Attribute names are UPPERCASE like the rest of the project."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
_PLACEHOLDERS = ("change_me", "changeme", "your_", "replace_me", "placeholder", "generate_me")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- Application ---
    APP_NAME: str = "StreamPulse"
    APP_ENV: Literal["development", "testing", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    CORS_ORIGINS: str = ""  # comma separated
    DATA_DIR: Path = BASE_DIR / "data"
    LOGS_DIR: Path = BASE_DIR / "logs"

    # --- Database (PostgreSQL, synchronous SQLAlchemy) ---
    DATABASE_URL: str
    DB_POOL_SIZE: int = 15
    DB_MAX_OVERFLOW: int = 15
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_STATEMENT_TIMEOUT_MS: int = 30_000
    DB_ECHO: bool = False

    # --- Security ---
    SECRET_KEY: str
    API_KEY_PEPPER: str
    ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "streampulse"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    LOGIN_IP_LIMIT_PER_MINUTE: int = 20
    PASSWORD_MIN_LENGTH: int = 10
    STREAM_TICKET_TTL_SECONDS: int = 30

    # --- Event ingestion ---
    SUPPORTED_SCHEMA_VERSIONS: str = "1.0"
    MAX_BATCH_SIZE: int = 100
    MAX_PAYLOAD_BYTES: int = 16_384
    MAX_REQUEST_BODY_BYTES: int = 2_097_152
    MAX_EVENT_AGE_DAYS: int = 365
    MAX_FUTURE_SKEW_SECONDS: int = 300
    DEFAULT_RATE_LIMIT_PER_MINUTE: int = 600
    IDEMPOTENCY_TTL_HOURS: int = 24

    # --- Queue / workers ---
    EVENT_QUEUE_MAXSIZE: int = 1000
    EVENT_WORKER_CONCURRENCY: int = 2
    EVENT_MAX_RETRIES: int = 3
    EVENT_RETRY_BASE_DELAY_SECONDS: float = 2.0
    EVENT_RETRY_MAX_DELAY_SECONDS: float = 60.0
    EVENT_PROCESSING_TIMEOUT_SECONDS: float = 30.0
    EVENT_SWEEP_INTERVAL_SECONDS: float = 5.0
    EVENT_SHUTDOWN_GRACE_SECONDS: float = 10.0

    # --- Live updates (SSE) ---
    SSE_HEARTBEAT_SECONDS: float = 15.0
    SSE_CLIENT_BUFFER_SIZE: int = 100
    SSE_MAX_CLIENTS: int = 50

    AUTO_SEED_RBAC: bool = True

    @field_validator("DATABASE_URL")
    @classmethod
    def _db_url(cls, v: str) -> str:
        if v.startswith("postgresql+asyncpg://"):
            raise ValueError("this project uses synchronous SQLAlchemy: use postgresql+psycopg2:// (or postgresql://)")
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+psycopg2://", 1)
        if not v.startswith("postgresql+psycopg2://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return v

    @field_validator("SECRET_KEY", "API_KEY_PEPPER")
    @classmethod
    def _secret_len(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("must be at least 32 characters (run: python -m scripts.generate_secrets)")
        return v

    @model_validator(mode="after")
    def _no_placeholders_in_production(self) -> "Settings":
        if self.APP_ENV == "production":
            for name in ("SECRET_KEY", "API_KEY_PEPPER"):
                if any(m in getattr(self, name).lower() for m in _PLACEHOLDERS):
                    raise ValueError(f"{name} still contains a placeholder value")
        return self

    @property
    def CORS_ORIGIN_LIST(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def SCHEMA_VERSIONS(self) -> frozenset[str]:
        return frozenset(v.strip() for v in self.SUPPORTED_SCHEMA_VERSIONS.split(",") if v.strip())

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.APP_ENV == "production"


settings = Settings()  # type: ignore[call-arg]
