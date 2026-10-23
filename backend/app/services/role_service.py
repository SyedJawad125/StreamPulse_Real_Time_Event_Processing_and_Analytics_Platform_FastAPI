"""Role and permission management."""
from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.schemas.role import RoleCreate, RoleUpdate
from app.services import audit_service


async def list_roles(session: AsyncSession) -> list[Role]:
    return list((await session.scalars(select(Role).order_by(Role.code_name))).all())


async def list_permissions(session: AsyncSession) -> list[Permission]:
    return list((await session.scalars(select(Permission).order_by(Permission.module_name, Permission.code_name))).all())


async def get_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await session.get(Role, role_id)
    if not role:
        raise NotFoundError("Role not found")
    return role


async def create_role(session: AsyncSession, request: Request, actor: User, data: RoleCreate) -> Role:
    if await session.scalar(select(Role.id).where((Role.code_name == data.code_name) | (Role.name == data.name))):
        raise ConflictError("Role name or code already exists", code="ROLE_EXISTS")
    role = Role(name=data.name, code_name=data.code_name, description=data.description, is_system=False, permissions=[])
    session.add(role)
    await session.flush()  # assign the UUID so the audit row can reference it
    audit_service.record(session, action="role.created", actor=actor, request=request, target_type="role",
                         target_id=role.id, details={"code_name": role.code_name})
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("Role name or code already exists", code="ROLE_EXISTS") from None
    return role


async def update_role(session: AsyncSession, request: Request, actor: User, role_id: uuid.UUID, data: RoleUpdate) -> Role:
    role = await get_role(session, role_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] and changes["name"] != role.name:
        if await session.scalar(select(Role.id).where(Role.name == changes["name"], Role.id != role.id)):
            raise ConflictError("Role name already exists", code="ROLE_EXISTS")
    for k, v in changes.items():
        if k == "name" and v is None:
            continue
        setattr(role, k, v)
    audit_service.record(session, action="role.updated", actor=actor, request=request, target_type="role",
                         target_id=role.id, details={"fields": sorted(changes)})
    await session.commit()
    return role


async def delete_role(session: AsyncSession, request: Request, actor: User, role_id: uuid.UUID) -> None:
    role = await get_role(session, role_id)
    if role.is_system:
        raise ForbiddenError("System roles cannot be deleted", code="SYSTEM_ROLE")
    audit_service.record(session, action="role.deleted", actor=actor, request=request, target_type="role",
                         target_id=role.id, details={"code_name": role.code_name})
    await session.delete(role)
    await session.commit()


async def set_permissions(
    session: AsyncSession, request: Request, actor: User, role_id: uuid.UUID, codes: list[str]
) -> Role:
    role = await get_role(session, role_id)
    if role.code_name == "ADMIN":
        raise ForbiddenError("ADMIN permissions are managed by the system", code="SYSTEM_ROLE")
    wanted = set(codes)
    perms = list((await session.scalars(select(Permission).where(Permission.code_name.in_(wanted)))).all()) if wanted else []
    missing = wanted - {p.code_name for p in perms}
    if missing:
        raise UnprocessableError(f"Unknown permission(s): {', '.join(sorted(missing))}", code="UNKNOWN_PERMISSION")
    before = sorted(p.code_name for p in role.permissions)
    role.permissions = perms
    audit_service.record(session, action="role.permissions_changed", actor=actor, request=request,
                         target_type="role", target_id=role.id,
                         details={"before": before, "after": sorted(wanted)})
    await session.commit()
    await session.refresh(role)
    return role
