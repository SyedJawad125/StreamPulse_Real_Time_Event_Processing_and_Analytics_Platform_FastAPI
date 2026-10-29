# app/models/mixins.py
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Session, declared_attr, relationship


class TimeStampMixin:
    """created_at / updated_at timestamps and soft delete."""

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self):
        self.deleted = False
        self.deleted_at = None

    @classmethod
    def get_active(cls, db: Session):
        return db.query(cls).filter(cls.deleted == False)  # noqa: E712

    @classmethod
    def get_deleted(cls, db: Session):
        return db.query(cls).filter(cls.deleted == True)  # noqa: E712

    @classmethod
    def get_all_including_deleted(cls, db: Session):
        return db.query(cls)


class UserStampMixin:
    """created_by / updated_by / deleted_by user references."""

    @declared_attr
    def created_by_user_id(cls):
        return Column(Integer, ForeignKey("users.id"), nullable=True)

    @declared_attr
    def updated_by_user_id(cls):
        return Column(Integer, ForeignKey("users.id"), nullable=True)

    @declared_attr
    def deleted_by_user_id(cls):
        return Column(Integer, ForeignKey("users.id"), nullable=True)

    @declared_attr
    def creator(cls):
        # Note: back_populates are manually defined in User model for each entity type
        return relationship("User", foreign_keys=lambda: [cls.created_by_user_id])

    @declared_attr
    def updater(cls):
        # Note: back_populates are manually defined in User model for each entity type
        return relationship("User", foreign_keys=lambda: [cls.updated_by_user_id])

    @declared_attr
    def deleter(cls):
        # Note: back_populates are manually defined in User model for each entity type
        return relationship("User", foreign_keys=lambda: [cls.deleted_by_user_id])


class TimeUserStampMixin(TimeStampMixin, UserStampMixin):
    """Timestamps + user stamps."""

    def soft_delete(self, user_id: int = None):
        super().soft_delete()
        if user_id:
            self.deleted_by_user_id = user_id
