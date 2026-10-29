# app/schemas/audit.py
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    actor_user_id: Optional[int] = None
    actor_email: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    success: bool
    ip_address: Optional[str] = None
    request_id: Optional[str] = None
    details: dict[str, Any]


class PaginatedAuditLogs(BaseModel):
    count: int
    data: List[AuditLogOut]


class AuditLogListResponse(BaseModel):
    status: str
    result: PaginatedAuditLogs
