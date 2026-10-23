from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import PERMISSIONS_MANAGE
from app.dependencies import get_db, require_permissions
from app.schemas.role import PermissionOut
from app.services import role_service
from app.services.auth_service import CurrentUser

router = APIRouter(prefix="/permissions", tags=["Permissions"])


@router.get("", response_model=list[PermissionOut], summary="List the permission catalogue")
async def list_permissions(_: CurrentUser = Depends(require_permissions(PERMISSIONS_MANAGE)),
                           session: AsyncSession = Depends(get_db)) -> list[PermissionOut]:
    return [PermissionOut.model_validate(p) for p in await role_service.list_permissions(session)]
