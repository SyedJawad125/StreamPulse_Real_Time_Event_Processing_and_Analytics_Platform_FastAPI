"""Create the FIRST administrator (and seed roles/permissions). Run locally with database access.

Usage (PowerShell):
    python -m scripts.bootstrap_admin --username admin --email admin@example.com
The password is requested interactively (hidden). For automation you may set the
BOOTSTRAP_ADMIN_PASSWORD environment variable instead - never pass it on the command line.

Safety: refuses to run if an active administrator already exists (use --allow-additional to override).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import func, select

from app.config import get_settings
from app.database import create_engine, create_session_factory
from app.models.role import Role, user_roles
from app.models.user import User
from app.schemas.user import UserCreate
from app.services import audit_service, user_service
from app.services.rbac_seed import seed_rbac


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        await seed_rbac(factory)
        async with factory() as session:
            existing = await session.scalar(
                select(func.count(User.id)).join(user_roles, user_roles.c.user_id == User.id)
                .join(Role, Role.id == user_roles.c.role_id).where(Role.code_name == "ADMIN", User.is_active.is_(True))
            )
            if existing and not args.allow_additional:
                print(f"An active administrator already exists ({existing}). Use --allow-additional to add another.")
                return 1

            password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
            if not password:
                password = getpass.getpass("Admin password (min 12 chars, letters+digits): ")
                if password != getpass.getpass("Repeat password: "):
                    print("Passwords do not match.")
                    return 1
            data = UserCreate(username=args.username, email=args.email, password=password,
                              first_name=args.first_name, last_name=args.last_name, is_verified=True,
                              role_codes=["ADMIN"])
            user = await user_service.create_user(session, settings, None, None, data)
            audit_service.record(session, action="admin.bootstrap", target_type="user", target_id=user.id,
                                 details={"username": user.username, "via": "scripts.bootstrap_admin"})
            await session.commit()
            print(f"Administrator '{user.username}' created. You can now log in at POST /api/v1/auth/login.")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--first-name", default=None)
    parser.add_argument("--last-name", default=None)
    parser.add_argument("--allow-additional", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
