import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Uuid, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin
from app.models.role import Role, user_roles


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped on password change; tokens carrying an older version are rejected.
    token_version: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin", order_by=Role.code_name)

    @property
    def permission_codes(self) -> frozenset[str]:
        return frozenset(p.code_name for r in self.roles for p in r.permissions)

    @property
    def role_codes(self) -> list[str]:
        return [r.code_name for r in self.roles]
