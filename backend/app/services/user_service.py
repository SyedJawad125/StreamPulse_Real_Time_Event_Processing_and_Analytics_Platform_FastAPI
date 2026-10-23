"""User management."""
from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.security import hash_password_async
from app.models.role import Role, user_roles
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.services import audit_service


async def _roles_by_codes(session: AsyncSession, codes: list[str]) -> list[Role]:
    wanted = {c.strip().upper() for c in codes}
    if not wanted:
        return []
    roles = list((await session.scalars(select(Role).where(Role.code_name.in_(wanted)))).all())
    missing = wanted - {r.code_name for r in roles}
    if missing:
        raise UnprocessableError(f"Unknown role(s): {', '.join(sorted(missing))}", code="UNKNOWN_ROLE")
    return roles


async def _ensure_other_active_admin(session: AsyncSession, excluding: uuid.UUID) -> None:
    """Never allow the system to be left without an active administrator."""
    count = await session.scalar(
        select(func.count(User.id))
        .join(user_roles, user_roles.c.user_id == User.id)
        .join(Role, Role.id == user_roles.c.role_id)
        .where(Role.code_name == "ADMIN", User.is_active.is_(True), User.id != excluding)
    )
    if not count:
        raise ConflictError("This would leave no active administrator", code="LAST_ADMIN")


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if not user:
        raise NotFoundError("User not found")
    return user


async def list_users(
    session: AsyncSession, *, q: str | None, is_active: bool | None, role_code: str | None, limit: int, offset: int
) -> tuple[list[User], int]:
    stmt = select(User)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(User.username.ilike(like) | User.email.ilike(like))
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if role_code:
        stmt = stmt.where(User.id.in_(
            select(user_roles.c.user_id).join(Role, Role.id == user_roles.c.role_id).where(Role.code_name == role_code.upper())
        ))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = (await session.scalars(stmt.order_by(User.created_at.desc(), User.id).limit(limit).offset(offset))).all()
    return list(items), total


async def create_user(
    session: AsyncSession, settings: Settings, request: Request | None, actor: User | None, data: UserCreate
) -> User:
    if len(data.password) < settings.password_min_length:
        raise UnprocessableError(f"Password must be at least {settings.password_min_length} characters", code="PASSWORD_WEAK")
    if data.username in data.password.lower():
        raise UnprocessableError("Password must not contain the username", code="PASSWORD_WEAK")
    if await session.scalar(select(User.id).where((User.username == data.username) | (User.email == data.email))):
        raise ConflictError("Username or email already in use", code="USER_EXISTS")
    roles = await _roles_by_codes(session, data.role_codes)
    user = User(
        username=data.username, email=data.email, first_name=data.first_name, last_name=data.last_name,
        is_verified=data.is_verified, password_hash=await hash_password_async(data.password), roles=roles,
    )
    session.add(user)
    await session.flush()  # assign the UUID so the audit row can reference it
    audit_service.record(session, action="user.created", actor=actor, request=request, target_type="user",
                         target_id=user.id, details={"username": user.username, "roles": data.role_codes})
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("Username or email already in use", code="USER_EXISTS") from None
    return user


async def update_user(
    session: AsyncSession, request: Request, actor: User, user_id: uuid.UUID, data: UserUpdate
) -> User:
    user = await get_user(session, user_id)
    changes = data.model_dump(exclude_unset=True)
    if "email" in changes and changes["email"] and changes["email"] != user.email:
        if await session.scalar(select(User.id).where(User.email == changes["email"], User.id != user.id)):
            raise ConflictError("Email already in use", code="USER_EXISTS")
    for field, value in changes.items():
        if field == "email" and value is None:
            continue
        setattr(user, field, value)
    audit_service.record(session, action="user.updated", actor=actor, request=request, target_type="user",
                         target_id=user.id, details={"fields": sorted(changes)})
    await session.commit()
    return user


async def set_active(session: AsyncSession, request: Request, actor: User, user_id: uuid.UUID, active: bool) -> User:
    user = await get_user(session, user_id)
    if not active:
        if user.id == actor.id:
            raise ForbiddenError("You cannot deactivate your own account", code="SELF_DEACTIVATION")
        if "ADMIN" in user.role_codes and user.is_active:
            await _ensure_other_active_admin(session, user.id)
    user.is_active = active
    if active:
        user.failed_login_attempts = 0
        user.locked_until = None
    audit_service.record(session, action="user.activated" if active else "user.deactivated", actor=actor,
                         request=request, target_type="user", target_id=user.id)
    await session.commit()
    return user


async def set_roles(
    session: AsyncSession, request: Request, actor: User, user_id: uuid.UUID, role_codes: list[str]
) -> User:
    user = await get_user(session, user_id)
    roles = await _roles_by_codes(session, role_codes)
    if "ADMIN" in user.role_codes and "ADMIN" not in {r.code_name for r in roles} and user.is_active:
        await _ensure_other_active_admin(session, user.id)
    before = user.role_codes
    user.roles = roles
    audit_service.record(session, action="user.roles_changed", actor=actor, request=request, target_type="user",
                         target_id=user.id, details={"before": before, "after": sorted(r.code_name for r in roles)})
    await session.commit()
    await session.refresh(user)
    return user
