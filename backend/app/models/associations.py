# app/models/associations.py
# Server-side timestamp defaults keep migrations and raw inserts safe.
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Table, text

from app.database import Base

# Roles <-> permissions
role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False),
    extend_existing=True,
)

# Users <-> permissions (permissions granted directly to a user, on top of the role's)
user_permission = Table(
    "user_permission",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False),
    extend_existing=True,
)
