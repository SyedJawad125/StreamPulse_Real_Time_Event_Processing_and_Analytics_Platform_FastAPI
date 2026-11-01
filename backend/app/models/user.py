# app/models/user.py
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, false, true
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.associations import user_permission
from app.models.mixins import TimeStampMixin


class User(TimeStampMixin, Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True, nullable=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, server_default=true(), nullable=False)
    is_superuser = Column(Boolean, server_default=false(), nullable=False)

    # --- authentication hardening ---
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempts = Column(Integer, server_default="0", nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    # Bumped on password change / forced logout: tokens carrying an older version stop working.
    token_version = Column(Integer, server_default="0", nullable=False)

    # Role (one-to-many: a user has one role)
    role_id = Column(Integer, ForeignKey("roles.id"))
    role = relationship("Role", back_populates="users", foreign_keys=[role_id])

    # Permissions granted directly to the user (many-to-many)
    permissions = relationship("Permission", secondary=user_permission, back_populates="users")

    # Employee relationship (one-to-one: a user can have one employee profile)
    employee = relationship("Employee", back_populates="user", uselist=False, foreign_keys="Employee.user_id")

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"
