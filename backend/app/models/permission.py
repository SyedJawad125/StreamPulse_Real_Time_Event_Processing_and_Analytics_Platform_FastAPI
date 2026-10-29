# app/models/permission.py
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.associations import role_permission, user_permission
from app.models.mixins import TimeUserStampMixin


class Permission(TimeUserStampMixin, Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    code = Column(String(50), nullable=False, unique=True)
    module_name = Column(String(50), nullable=True)

    # Roles / users holding this permission. Loaded on demand (use joinedload/selectinload where a response needs
    # them) so that loading a role's permissions never drags every user of every permission into memory.
    roles = relationship("Role", secondary=role_permission, back_populates="permissions")
    users = relationship("User", secondary=user_permission, back_populates="permissions")

    def __repr__(self):
        return f"<Permission(id={self.id}, name='{self.name}', code='{self.code}')>"
