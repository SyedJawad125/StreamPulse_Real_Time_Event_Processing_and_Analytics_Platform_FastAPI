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

    # Objects created / updated / deleted by this user (mirror UserStampMixin's back_populates)
    created_roles = relationship("Role", back_populates="creator", foreign_keys="Role.created_by_user_id")
    updated_roles = relationship("Role", back_populates="updater", foreign_keys="Role.updated_by_user_id")
    deleted_roles = relationship("Role", back_populates="deleter", foreign_keys="Role.deleted_by_user_id")

    created_permissions = relationship("Permission", back_populates="creator", foreign_keys="Permission.created_by_user_id")
    updated_permissions = relationship("Permission", back_populates="updater", foreign_keys="Permission.updated_by_user_id")
    deleted_permissions = relationship("Permission", back_populates="deleter", foreign_keys="Permission.deleted_by_user_id")

    created_api_keys = relationship("APIKey", back_populates="creator", foreign_keys="APIKey.created_by_user_id")
    updated_api_keys = relationship("APIKey", back_populates="updater", foreign_keys="APIKey.updated_by_user_id")
    deleted_api_keys = relationship("APIKey", back_populates="deleter", foreign_keys="APIKey.deleted_by_user_id")

    # Employee relationship (one-to-one: a user can have one employee profile)
    employee = relationship("Employee", back_populates="user", uselist=False, foreign_keys="Employee.user_id")

    # Objects created / updated / deleted by this user (mirror UserStampMixin's back_populates)
    created_employees = relationship("Employee", back_populates="creator", foreign_keys="Employee.created_by_user_id")
    updated_employees = relationship("Employee", back_populates="updater", foreign_keys="Employee.updated_by_user_id")
    deleted_employees = relationship("Employee", back_populates="deleter", foreign_keys="Employee.deleted_by_user_id")

    # Image relationships
    created_images = relationship("Image", back_populates="creator", foreign_keys="Image.created_by_user_id")
    updated_images = relationship("Image", back_populates="updater", foreign_keys="Image.updated_by_user_id")
    deleted_images = relationship("Image", back_populates="deleter", foreign_keys="Image.deleted_by_user_id")

    # ImageCategory relationships
    created_image_categories = relationship("ImageCategory", back_populates="creator", foreign_keys="ImageCategory.created_by_user_id")
    updated_image_categories = relationship("ImageCategory", back_populates="updater", foreign_keys="ImageCategory.updated_by_user_id")
    deleted_image_categories = relationship("ImageCategory", back_populates="deleter", foreign_keys="ImageCategory.deleted_by_user_id")

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"
