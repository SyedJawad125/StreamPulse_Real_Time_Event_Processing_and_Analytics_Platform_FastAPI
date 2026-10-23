"""Permission catalogue and default role definitions (single source of truth)."""
from __future__ import annotations

from dataclasses import dataclass

# --- Permission codes ------------------------------------------------------
EVENTS_READ = "events.read"
EVENTS_READ_PAYLOAD = "events.read_payload"
EVENTS_INGEST = "events.ingest"  # API-key scope; also assignable to roles
EVENTS_REPROCESS = "events.reprocess"
ANALYTICS_READ = "analytics.read"
USERS_READ = "users.read"
USERS_MANAGE = "users.manage"
ROLES_MANAGE = "roles.manage"
PERMISSIONS_MANAGE = "permissions.manage"
API_KEYS_READ = "api_keys.read"
API_KEYS_MANAGE = "api_keys.manage"
AUDIT_LOGS_READ = "audit_logs.read"


@dataclass(frozen=True)
class PermissionDef:
    code_name: str
    name: str
    module_name: str
    description: str


PERMISSIONS: tuple[PermissionDef, ...] = (
    PermissionDef(EVENTS_READ, "Read events", "events", "List and inspect event records and attempts."),
    PermissionDef(EVENTS_READ_PAYLOAD, "Read event payloads", "events", "See event payload and metadata (otherwise redacted)."),
    PermissionDef(EVENTS_INGEST, "Ingest events", "events", "Submit events (API-key scope)."),
    PermissionDef(EVENTS_REPROCESS, "Reprocess events", "events", "Reprocess failed events and resolve dead letters."),
    PermissionDef(ANALYTICS_READ, "Read analytics", "analytics", "Query analytics endpoints and live stream."),
    PermissionDef(USERS_READ, "Read users", "users", "List users and roles."),
    PermissionDef(USERS_MANAGE, "Manage users", "users", "Create, update, (de)activate users and assign roles."),
    PermissionDef(ROLES_MANAGE, "Manage roles", "roles", "Create, update and delete custom roles."),
    PermissionDef(PERMISSIONS_MANAGE, "Manage permissions", "permissions", "View permissions and assign them to roles."),
    PermissionDef(API_KEYS_READ, "Read API keys", "api_keys", "List API-key metadata."),
    PermissionDef(API_KEYS_MANAGE, "Manage API keys", "api_keys", "Create, update and revoke API keys."),
    PermissionDef(AUDIT_LOGS_READ, "Read audit logs", "audit", "View the audit log."),
)

ALL_PERMISSION_CODES: frozenset[str] = frozenset(p.code_name for p in PERMISSIONS)


@dataclass(frozen=True)
class RoleDef:
    code_name: str
    name: str
    description: str
    permissions: frozenset[str]


ROLES: tuple[RoleDef, ...] = (
    RoleDef("ADMIN", "Administrator", "Full administrative access.", ALL_PERMISSION_CODES),
    RoleDef(
        "OPERATOR",
        "Operator",
        "Inspect events, review failures and reprocess eligible failed events.",
        frozenset({EVENTS_READ, EVENTS_READ_PAYLOAD, EVENTS_REPROCESS, ANALYTICS_READ}),
    ),
    RoleDef(
        "ANALYST",
        "Analyst",
        "Read analytics and event information (including payloads).",
        frozenset({EVENTS_READ, EVENTS_READ_PAYLOAD, ANALYTICS_READ}),
    ),
    RoleDef(
        "VIEWER",
        "Viewer",
        "Read-only access to events (payloads redacted) and analytics.",
        frozenset({EVENTS_READ, ANALYTICS_READ}),
    ),
)

# Scopes that may be placed on an API key.
API_KEY_SCOPES: frozenset[str] = frozenset({EVENTS_INGEST})
