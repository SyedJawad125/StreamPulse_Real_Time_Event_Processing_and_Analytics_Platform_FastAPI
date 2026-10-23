import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None = None
    actor_username: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    success: bool
    ip_address: str | None = None
    request_id: str | None = None
    details: dict[str, Any]
