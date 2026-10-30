# app/models/__init__.py
"""Import every model so Base.metadata is complete (needed by Alembic) and `models.User` etc. work."""
from app.models.associations import role_permission, user_permission
from app.models.api_key import APIKey
from app.models.audit_log import AuditLog
from app.models.auth_support import IdempotencyRecord, RevokedToken
from app.models.employee import Employee
from app.models.event import (AttemptOutcome, DeadLetterEvent, DeadLetterStatus, Event, EventStatus,
                              ProcessingAttempt)
from app.models.image import Image
from app.models.image_category import ImageCategory
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User

__all__ = [
    "role_permission", "user_permission", "APIKey", "AuditLog", "IdempotencyRecord", "RevokedToken",
    "AttemptOutcome", "DeadLetterEvent", "DeadLetterStatus", "Event", "EventStatus", "ProcessingAttempt",
    "Employee", "Image", "ImageCategory",
    "Permission", "Role", "User",
]
