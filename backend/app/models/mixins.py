# # app/models/mixins.py
# from datetime import datetime, timezone
# from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, event
# from sqlalchemy.orm import declared_attr, relationship, Session
# from sqlalchemy.ext.declarative import declared_attr


# class TimeStampMixin:
#     """Mixin for created_at, updated_at timestamps and soft delete"""
    
#     created_at = Column(
#         DateTime(timezone=True), 
#         default=lambda: datetime.now(timezone.utc), 
#         nullable=False
#     )
#     updated_at = Column(
#         DateTime(timezone=True), 
#         default=lambda: datetime.now(timezone.utc),
#         onupdate=lambda: datetime.now(timezone.utc),
#         nullable=False
#     )
#     deleted = Column(Boolean, default=False, nullable=False)
#     deleted_at = Column(DateTime(timezone=True), nullable=True)
    
#     def soft_delete(self):
#         """Soft delete this record"""
#         self.deleted = True
#         self.deleted_at = datetime.now(timezone.utc)
    
#     def restore(self):
#         """Restore a soft-deleted record"""
#         self.deleted = False
#         self.deleted_at = None
    
#     @classmethod
#     def get_active(cls, db: Session):
#         """Get all non-deleted records"""
#         return db.query(cls).filter(cls.deleted == False)
    
#     @classmethod
#     def get_deleted(cls, db: Session):
#         """Get all soft-deleted records"""
#         return db.query(cls).filter(cls.deleted == True)
    
#     @classmethod
#     def get_all_including_deleted(cls, db: Session):
#         """Get all records including deleted ones"""
#         return db.query(cls)


# class UserStampMixin:
#     """Mixin for created_by and updated_by user references"""
    
#     @declared_attr
#     def created_by_user_id(cls):
#         return Column(Integer, ForeignKey("users.id"), nullable=True)
    
#     @declared_attr
#     def updated_by_user_id(cls):
#         return Column(Integer, ForeignKey("users.id"), nullable=True)
    
#     @declared_attr
#     def deleted_by_user_id(cls):
#         return Column(Integer, ForeignKey("users.id"), nullable=True)
    
#     @declared_attr
#     def creator(cls):
#         return relationship(
#             "User", 
#             foreign_keys=lambda: [cls.created_by_user_id],
#             back_populates=f"{cls.__tablename__}_created"
#         )
    
#     @declared_attr
#     def updater(cls):
#         return relationship(
#             "User", 
#             foreign_keys=lambda: [cls.updated_by_user_id],
#             back_populates=f"{cls.__tablename__}_updated"
#         )
    
#     @declared_attr
#     def deleter(cls):
#         return relationship(
#             "User", 
#             foreign_keys=lambda: [cls.deleted_by_user_id],
#             back_populates=f"{cls.__tablename__}_deleted"
#         )


# class TimeUserStampMixin(TimeStampMixin, UserStampMixin):
#     """Combined mixin for both timestamps and user stamps"""
    
#     def soft_delete(self, user_id: int = None):
#         """Soft delete this record with user tracking"""
#         super().soft_delete()
#         if user_id:
#             self.deleted_by_user_id = user_id
    
#     pass




# app/models/mixins.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declared_attr, relationship, Session


class TimeStampMixin:
    """Mixin for created_at, updated_at timestamps and soft delete"""
    
    created_at = Column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc), 
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    def soft_delete(self):
        """Soft delete this record"""
        self.deleted = True
        self.deleted_at = datetime.now(timezone.utc)
    
    def restore(self):
        """Restore a soft-deleted record"""
        self.deleted = False
        self.deleted_at = None
    
    @classmethod
    def get_active(cls, db: Session):
        """Get all non-deleted records"""
        return db.query(cls).filter(cls.deleted == False)
    
    @classmethod
    def get_deleted(cls, db: Session):
        """Get all soft-deleted records"""
        return db.query(cls).filter(cls.deleted == True)
    
    @classmethod
    def get_all_including_deleted(cls, db: Session):
        """Get all records including deleted ones"""
        return db.query(cls)


class UserStampMixin:
    """Mixin for created_by and updated_by user references"""
    
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
        return relationship(
            "User", 
            foreign_keys=lambda: [cls.created_by_user_id],
            back_populates=f"created_{cls.__tablename__}"  # Changed: created_roles, created_permissions, etc.
        )
    
    @declared_attr
    def updater(cls):
        return relationship(
            "User", 
            foreign_keys=lambda: [cls.updated_by_user_id],
            back_populates=f"updated_{cls.__tablename__}"  # Changed: updated_roles, updated_permissions, etc.
        )
    
    @declared_attr
    def deleter(cls):
        return relationship(
            "User", 
            foreign_keys=lambda: [cls.deleted_by_user_id],
            back_populates=f"deleted_{cls.__tablename__}"  # Changed: deleted_roles, deleted_permissions, etc.
        )


class TimeUserStampMixin(TimeStampMixin, UserStampMixin):
    """Combined mixin for both timestamps and user stamps"""
    
    def soft_delete(self, user_id: int = None):
        """Soft delete this record with user tracking"""
        super().soft_delete()
        if user_id:
            self.deleted_by_user_id = user_id