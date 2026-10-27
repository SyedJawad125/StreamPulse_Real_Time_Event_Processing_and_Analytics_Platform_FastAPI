# app/seed.py
"""Permission catalogue + default roles, and idempotent seeding helpers.

Used by `add_permissions.py`, `populate.py` and (optionally) application startup (AUTO_SEED_RBAC).
`show_*` permissions are UI-visibility flags for the frontend; every other code is enforced on the server.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Permission, Role

logger = logging.getLogger(__name__)

INGEST_SCOPE = "ingest_event"  # API-key scope (not a dashboard permission)


def _p(name: str, code: str, module: str, description: str) -> dict:
    return {"name": name, "code": code, "module_name": module, "description": description}


PERMISSIONS: list[dict] = [
    # ---------- Role ----------
    _p("Show Role", "show_role", "Role", "User can see role"),
    _p("Create Role", "create_role", "Role", "User can create role"),
    _p("Read Role", "read_role", "Role", "User can read role"),
    _p("Update Role", "update_role", "Role", "User can update role"),
    _p("Delete Role", "delete_role", "Role", "User can delete role"),
    # ---------- User ----------
    _p("Show User", "show_user", "User", "User can see user"),
    _p("Create User", "create_user", "User", "User can create user"),
    _p("Read User", "read_user", "User", "User can read user"),
    _p("Update User", "update_user", "User", "User can update user"),
    _p("Delete User", "delete_user", "User", "User can delete user"),
    _p("Deactivate User", "toggle_user", "User", "User can activate/deactivate user"),
    # ---------- Permission ----------
    _p("Show Permission", "show_permission", "Permission", "User can see Permission"),
    _p("Create Permission", "create_permission", "Permission", "User can create Permission"),
    _p("Read Permission", "read_permission", "Permission", "User can read Permission"),
    _p("Update Permission", "update_permission", "Permission", "User can update Permission"),
    _p("Delete Permission", "delete_permission", "Permission", "User can delete Permission"),
    # ---------- Event ----------
    _p("Read Event", "read_event", "Event", "User can list and inspect events"),
    _p("Read Event Payload", "read_event_payload", "Event", "User can see event payload/metadata (otherwise redacted)"),
    _p("Reprocess Event", "reprocess_event", "Event", "User can reprocess failed events and resolve dead letters"),
    # ---------- Analytics ----------
    _p("Read Analytics", "read_analytics", "Analytics", "User can read analytics and the live event stream"),
    # ---------- API key ----------
    _p("Create API Key", "create_api_key", "API Key", "User can create API keys"),
    _p("Read API Key", "read_api_key", "API Key", "User can read API-key metadata"),
    _p("Update API Key", "update_api_key", "API Key", "User can update/revoke API keys"),
    _p("Delete API Key", "delete_api_key", "API Key", "User can delete API keys"),
    # ---------- Audit ----------
    _p("Read Audit Log", "read_audit_log", "Audit", "User can read the audit log"),
    # ---------- Employee ----------
    _p("Show Employee", "show_employee", "Employee", "User can see employee"),
    _p("Create Employee", "create_employee", "Employee", "User can create employee"),
    _p("Read Employee", "read_employee", "Employee", "User can read employee"),
    _p("Update Employee", "update_employee", "Employee", "User can update employee"),
    _p("Delete Employee", "delete_employee", "Employee", "User can delete employee"),
    # ---------- Image ----------
    _p("Show Image", "show_image", "Image", "User can see image"),
    _p("Create Image", "create_image", "Image", "User can create image"),
    _p("Read Image", "read_image", "Image", "User can read image"),
    _p("Update Image", "update_image", "Image", "User can update image"),
    _p("Delete Image", "delete_image", "Image", "User can delete image"),
    # ---------- Image Category ----------
    _p("Show Image Category", "show_image_category", "ImageCategory", "User can see image category"),
    _p("Create Image Category", "create_image_category", "ImageCategory", "User can create image category"),
    _p("Read Image Category", "read_image_category", "ImageCategory", "User can read image category"),
    _p("Update Image Category", "update_image_category", "ImageCategory", "User can update image category"),
    _p("Delete Image Category", "delete_image_category", "ImageCategory", "User can delete image category"),
]

ALL_CODES = [p["code"] for p in PERMISSIONS]

# code -> (name, description, permission codes)  ("su" always receives every permission)
DEFAULT_ROLES: dict[str, tuple[str, str, list[str]]] = {
    "su": ("Super", "Super Admin role with all permissions", ALL_CODES),
    "operator": ("Operator", "Inspect events, review failures and reprocess eligible failed events",
                 ["read_event", "read_event_payload", "reprocess_event", "read_analytics"]),
    "analyst": ("Analyst", "Read analytics and event information (including payloads)",
                ["read_event", "read_event_payload", "read_analytics"]),
    "viewer": ("Viewer", "Read-only access to events (payloads redacted) and analytics",
               ["read_event", "read_analytics"]),
}


def seed_permissions(db: Session, verbose: bool = False) -> tuple[int, int]:
    """Create missing permissions. Returns (added, skipped)."""
    existing = {code for (code,) in db.query(Permission.code).all()}
    added = 0
    for data in PERMISSIONS:
        if data["code"] in existing:
            if verbose:
                print(f"⏩ Skipped (already exists): {data['name']}")
            continue
        db.add(Permission(**data))
        added += 1
        if verbose:
            print(f"✅ Added: {data['name']}")
    db.commit()
    return added, len(PERMISSIONS) - added


def seed_roles(db: Session, reset: bool = False, verbose: bool = False) -> dict[str, Role]:
    """Create missing default roles.

    - "su" is always synchronised to hold every permission.
    - Other existing roles keep admin customisations unless `reset=True` (then they are restored to the defaults).
    """
    perms = {p.code: p for p in db.query(Permission).filter(Permission.deleted == False).all()}  # noqa: E712
    roles: dict[str, Role] = {}
    for code, (name, description, codes) in DEFAULT_ROLES.items():
        role = db.query(Role).filter(Role.code == code).first()
        wanted = [perms[c] for c in codes if c in perms]
        if role is None:
            role = Role(name=name, code=code, description=description)
            role.permissions = wanted
            db.add(role)
            if verbose:
                print(f"✅ Created {name} role ({len(wanted)} permissions)")
        elif code == "su" or reset:
            role.permissions = wanted
            if role.deleted:
                role.restore()
            if verbose:
                print(f"✅ Synchronised {name} role ({len(wanted)} permissions)")
        elif verbose:
            print(f"⏩ Kept existing {name} role")
        roles[code] = role
    db.commit()
    return roles
