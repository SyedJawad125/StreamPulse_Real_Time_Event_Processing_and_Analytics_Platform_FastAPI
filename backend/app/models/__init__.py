"""Import every model so `Base.metadata` is complete (needed by Alembic)."""
from app.models.api_key import APIKey
from app.models.audit_log import AuditLog
from app.models.auth_support import IdempotencyRecord, RevokedToken
from app.models.event import (
    AttemptOutcome,
    DeadLetterEvent,
    DeadLetterStatus,
    Event,
    EventStatus,
    ProcessingAttempt,
)
from app.models.permission import Permission, role_permissions
from app.models.role import Role, user_roles
from app.models.user import User

__all__ = [
    "APIKey", "AuditLog", "IdempotencyRecord", "RevokedToken", "AttemptOutcome", "DeadLetterEvent",
    "DeadLetterStatus", "Event", "EventStatus", "ProcessingAttempt", "Permission", "role_permissions",
    "Role", "user_roles", "User",
]
