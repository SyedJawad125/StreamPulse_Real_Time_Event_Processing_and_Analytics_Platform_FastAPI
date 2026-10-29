# app/models/role.py
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.associations import role_permission
from app.models.mixins import TimeUserStampMixin


class Role(TimeUserStampMixin, Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    code = Column(String(50), nullable=True, unique=True)

    # Users with this role (one-to-many)
    users = relationship("User", back_populates="role", foreign_keys="[User.role_id]")

    # Permissions of this role (many-to-many); eager so auth checks and responses never lazy-load.
    permissions = relationship("Permission", secondary=role_permission, back_populates="roles", lazy="selectin")

    def __repr__(self):
        return f"<Role(id={self.id}, name='{self.name}', code='{self.code}')>"
