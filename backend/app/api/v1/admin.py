import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AUDIT_LOGS_READ
from app.dependencies import get_db, require_permissions
from app.schemas.audit import AuditLogOut
from app.schemas.common import Page
from app.services import audit_service
from app.services.auth_service import CurrentUser

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/audit-logs", response_model=Page[AuditLogOut], summary="Browse the audit trail (newest first)")
async def audit_logs(
    action: str | None = Query(None, max_length=100), actor_user_id: uuid.UUID | None = None,
    success: bool | None = None, from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    _: CurrentUser = Depends(require_permissions(AUDIT_LOGS_READ)), session: AsyncSession = Depends(get_db),
) -> Page[AuditLogOut]:
    items, total = await audit_service.list_logs(session, action=action, actor_user_id=actor_user_id, success=success,
                                                 start=from_, end=to, limit=limit, offset=offset)
    return Page(items=[AuditLogOut.model_validate(i) for i in items], total=total, limit=limit, offset=offset)
