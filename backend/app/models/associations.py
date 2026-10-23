# from sqlalchemy import Table, Column, Integer, ForeignKey
# from app.database import Base

# # Association between users and roles
# user_role = Table(
#     'user_role',
#     Base.metadata,
#     Column('user_id', Integer, ForeignKey('users.id')),
#     Column('role_id', Integer, ForeignKey('roles.id'))
# )




# # app/models/associations.py
# from sqlalchemy import Table, Column, Integer, ForeignKey
# from app.database import Base

# # Association between roles and permissions
# role_permission = Table(
#     'role_permission',
#     Base.metadata,
#     Column('role_id', Integer, ForeignKey('roles.id'), primary_key=True),
#     Column('permission_id', Integer, ForeignKey('permissions.id'), primary_key=True)
# )

# # Association between users and permissions (direct permissions)
# user_permission = Table(
#     "user_permission",
#     Base.metadata,
#     Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
#     Column("permission_id", Integer, ForeignKey("permissions.id"), primary_key=True)
# )

# # Association between users and roles (if needed for many-to-many)
# user_role = Table(
#     'user_role',
#     Base.metadata,
#     Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
#     Column('role_id', Integer, ForeignKey('roles.id'), primary_key=True)
# )




# app/models/associations.py
# ✅ CORRECTED VERSION with server_default to prevent migration issues

from sqlalchemy import Table, Column, Integer, ForeignKey, DateTime, text
from app.database import Base


# Association between roles and permissions
# ✅ Uses server_default to ensure database sets the timestamp
role_permission = Table(
    'role_permission',
    Base.metadata,
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), 
           server_default=text('CURRENT_TIMESTAMP'),  # ✅ KEY FIX: Database-level default
           nullable=False),
    extend_existing=True
)

# Association between users and permissions (direct permissions)
user_permission = Table(
    "user_permission",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete='CASCADE'), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), 
           server_default=text('CURRENT_TIMESTAMP'),  # ✅ KEY FIX: Database-level default
           nullable=False),
    extend_existing=True
)

# Association between users and roles (if using many-to-many)
# NOTE: This is only needed if a user can have multiple roles
# If using simple role_id FK in users table, you don't need this
user_role = Table(
    'user_role',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime(timezone=True), 
           server_default=text('CURRENT_TIMESTAMP'),  # ✅ KEY FIX: Database-level default
           nullable=False),
    extend_existing=True
)