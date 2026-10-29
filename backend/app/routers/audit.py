# app/routers/audit.py
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import database, schemas
from app.crud import audit as crud
from app.dependencies.permission import require

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/v1/audit-log/", response_model=schemas.AuditLogListResponse, dependencies=[require("read_audit_log")])
def list_audit_logs(action: str | None = Query(None, max_length=100), actor_user_id: int | None = None,
                    success: bool | None = None, from_: datetime | None = Query(None, alias="from"),
                    to: datetime | None = None, skip: int = 0, limit: int = Query(10, ge=1, le=200),
                    db: Session = Depends(database.get_db)):
    """The audit trail, newest first."""
    items, total = crud.list_logs(db, action=action, actor_user_id=actor_user_id, success=success, start=from_,
                                  end=to, skip=skip, limit=limit)
    return {"status": "success", "result": {"count": total, "data": [schemas.AuditLogOut.model_validate(i) for i in items]}}
