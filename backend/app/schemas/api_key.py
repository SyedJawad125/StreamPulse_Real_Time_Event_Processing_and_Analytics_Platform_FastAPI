import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    customer_id: str | None = Field(default=None, max_length=100, description="Restricts the key to this tenant")
    scopes: list[str] = Field(default_factory=lambda: ["events.ingest"], max_length=10)
    expires_at: AwareDatetime | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100_000)
    daily_event_quota: int | None = Field(default=None, ge=1)


class APIKeyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    expires_at: AwareDatetime | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100_000)
    daily_event_quota: int | None = Field(default=None, ge=1)


class APIKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None = None
    key_prefix: str
    owner_user_id: uuid.UUID | None = None
    customer_id: str | None = None
    scopes: list[str]
    is_active: bool
    revoked_at: datetime | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    rate_limit_per_minute: int
    daily_event_quota: int | None = None
    created_at: datetime
    updated_at: datetime


class APIKeyCreated(APIKeyOut):
    key: str = Field(description="Plaintext API key. Shown ONCE; store it securely.")
