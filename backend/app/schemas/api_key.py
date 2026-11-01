# app/schemas/api_key.py
from datetime import datetime
from typing import List, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.schemas.base import TimeUserStampSchema


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    customer_id: Optional[str] = Field(None, max_length=100, description="Locks the key to this tenant")
    scopes: List[str] = Field(default_factory=lambda: ["ingest_event"], max_length=10)
    expires_at: Optional[AwareDatetime] = None
    rate_limit_per_minute: Optional[int] = Field(None, ge=1, le=100_000)
    daily_event_quota: Optional[int] = Field(None, ge=1)
    model_config = ConfigDict(extra="forbid")


class APIKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    expires_at: Optional[AwareDatetime] = None
    rate_limit_per_minute: Optional[int] = Field(None, ge=1, le=100_000)
    daily_event_quota: Optional[int] = Field(None, ge=1)
    model_config = ConfigDict(extra="forbid")


class APIKeyOut(TimeUserStampSchema):
    id: int
    name: str
    description: Optional[str] = None
    key_prefix: str
    customer_id: Optional[str] = None
    scopes: List[str]
    is_active: bool
    revoked_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    rate_limit_per_minute: int
    daily_event_quota: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class APIKeyCreated(APIKeyOut):
    key: str = Field(description="Plaintext API key. Shown ONCE; store it securely.")


class PaginatedAPIKeys(BaseModel):
    count: int
    data: List[APIKeyOut]


class APIKeyListResponse(BaseModel):
    status: str
    result: PaginatedAPIKeys
