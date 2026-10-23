import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import PERMISSIONS_MANAGE, ROLES_MANAGE, USERS_READ
from app.dependencies import get_db, require_any_permission, require_permissions
from app.schemas.role import RoleCreate, RoleOut, RolePermissionsUpdate, RoleUpdate
from app.services import role_service
from app.services.auth_service import CurrentUser

router = APIRouter(prefix="/roles", tags=["Roles"])


@router.get("", response_model=list[RoleOut])
async def list_roles(_: CurrentUser = Depends(require_any_permission(USERS_READ, ROLES_MANAGE)),
                     session: AsyncSession = Depends(get_db)) -> list[RoleOut]:
    return [RoleOut.model_validate(r) for r in await role_service.list_roles(session)]


@router.post("", response_model=RoleOut, status_code=201)
async def create_role(body: RoleCreate, request: Request, current: CurrentUser = Depends(require_permissions(ROLES_MANAGE)),
                      session: AsyncSession = Depends(get_db)) -> RoleOut:
    return RoleOut.model_validate(await role_service.create_role(session, request, current.user, body))


@router.get("/{role_id}", response_model=RoleOut)
async def get_role(role_id: uuid.UUID, _: CurrentUser = Depends(require_any_permission(USERS_READ, ROLES_MANAGE)),
                   session: AsyncSession = Depends(get_db)) -> RoleOut:
    return RoleOut.model_validate(await role_service.get_role(session, role_id))


@router.patch("/{role_id}", response_model=RoleOut)
async def update_role(role_id: uuid.UUID, body: RoleUpdate, request: Request,
                      current: CurrentUser = Depends(require_permissions(ROLES_MANAGE)),
                      session: AsyncSession = Depends(get_db)) -> RoleOut:
    return RoleOut.model_validate(await role_service.update_role(session, request, current.user, role_id, body))


@router.delete("/{role_id}", status_code=204, summary="Delete a custom role (system roles are protected)")
async def delete_role(role_id: uuid.UUID, request: Request, current: CurrentUser = Depends(require_permissions(ROLES_MANAGE)),
                      session: AsyncSession = Depends(get_db)) -> Response:
    await role_service.delete_role(session, request, current.user, role_id)
    return Response(status_code=204)


@router.put("/{role_id}/permissions", response_model=RoleOut, summary="Replace a role's permissions")
async def set_role_permissions(role_id: uuid.UUID, body: RolePermissionsUpdate, request: Request,
                               current: CurrentUser = Depends(require_permissions(PERMISSIONS_MANAGE)),
                               session: AsyncSession = Depends(get_db)) -> RoleOut:
    return RoleOut.model_validate(
        await role_service.set_permissions(session, request, current.user, role_id, body.permission_codes))
