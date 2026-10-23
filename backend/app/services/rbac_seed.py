"""Idempotent seeding of permissions and the default roles.

- Missing permissions are created.
- Missing default roles are created with their default permissions.
- ADMIN is always synchronised to hold *every* permission.
- Existing non-ADMIN roles are never overwritten (admin customisations survive).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.permissions import PERMISSIONS, ROLES
from app.models.permission import Permission
from app.models.role import Role

logger = logging.getLogger(__name__)


async def seed_rbac_in_session(session: AsyncSession) -> None:
    existing = {p.code_name: p for p in (await session.scalars(select(Permission))).all()}
    for pdef in PERMISSIONS:
        if pdef.code_name not in existing:
            perm = Permission(
                name=pdef.name, code_name=pdef.code_name, module_name=pdef.module_name, description=pdef.description
            )
            session.add(perm)
            existing[pdef.code_name] = perm
    await session.flush()

    roles = {r.code_name: r for r in (await session.scalars(select(Role))).all()}
    for rdef in ROLES:
        role = roles.get(rdef.code_name)
        if role is None:
            session.add(
                Role(
                    name=rdef.name,
                    code_name=rdef.code_name,
                    description=rdef.description,
                    is_system=True,
                    permissions=[existing[c] for c in sorted(rdef.permissions)],
                )
            )
        elif rdef.code_name == "ADMIN":
            role.is_system = True
            role.permissions = [existing[c] for c in sorted(rdef.permissions)]
    await session.commit()


async def seed_rbac(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await seed_rbac_in_session(session)
    logger.info("RBAC seed complete")
