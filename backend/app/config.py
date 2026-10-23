"""Application configuration loaded from environment variables / `.env`."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

_PLACEHOLDER_MARKERS = ("change_me", "changeme", "your_", "replace_me", "placeholder")


class Settings(BaseSettings):
    """All runtime configuration. Environment variables override `.env`."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "StreamPulse"
    app_env: Literal["development", "testing", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: str = ""  # comma-separated list, e.g. http://localhost:3000
    data_dir: Path = BASE_DIR / "data"
    logs_dir: Path = BASE_DIR / "logs"

    # --- Database ----------------------------------------------------------
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    db_statement_timeout_ms: int = 30_000
    db_echo: bool = False

    # --- Security ----------------------------------------------------------
    secret_key: SecretStr  # signs JWT access tokens
    api_key_pepper: SecretStr  # HMAC key used when hashing API keys
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "streampulse"
    access_token_expire_minutes: int = 30
    login_max_failed_attempts: int = 5
    login_lockout_minutes: int = 15
    login_ip_limit_per_minute: int = 20
    password_min_length: int = 12
    stream_ticket_ttl_seconds: int = 30

    # --- Event ingestion ---------------------------------------------------
    supported_schema_versions: str = "1.0"
    max_batch_size: int = 100
    max_payload_bytes: int = 16_384
    max_request_body_bytes: int = 2_097_152
    max_event_age_days: int = 365
    max_future_skew_seconds: int = 300
    default_rate_limit_per_minute: int = 600
    idempotency_ttl_hours: int = 24

    # --- Queue / workers ---------------------------------------------------
    event_queue_maxsize: int = 1000
    event_worker_concurrency: int = 2
    event_max_retries: int = 3
    event_retry_base_delay_seconds: float = 2.0
    event_retry_max_delay_seconds: float = 60.0
    event_processing_timeout_seconds: float = 30.0
    event_sweep_interval_seconds: float = 5.0
    event_shutdown_grace_seconds: float = 10.0

    # --- Live updates (SSE) -----------------------------------------------
    sse_heartbeat_seconds: float = 15.0
    sse_client_buffer_size: int = 100
    sse_max_clients: int = 100

    # --- Bootstrap ---------------------------------------------------------
    auto_seed_rbac: bool = True

    @field_validator("database_url")
    @classmethod
    def _check_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must start with 'postgresql+asyncpg://'")
        return v

    @field_validator("secret_key", "api_key_pepper")
    @classmethod
    def _check_secret_length(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters (run scripts/generate_secrets.py)")
        return v

    @model_validator(mode="after")
    def _reject_placeholders_in_production(self) -> "Settings":
        if self.app_env == "production":
            for name in ("secret_key", "api_key_pepper"):
                value = getattr(self, name).get_secret_value().lower()
                if any(marker in value for marker in _PLACEHOLDER_MARKERS):
                    raise ValueError(f"{name.upper()} still contains a placeholder value")
        return self

    # --- Derived helpers ---------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def schema_versions(self) -> frozenset[str]:
        return frozenset(v.strip() for v in self.supported_schema_versions.split(",") if v.strip())

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
