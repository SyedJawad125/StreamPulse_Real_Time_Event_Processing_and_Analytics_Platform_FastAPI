# app/schemas/base.py
"""Base schemas for common fields"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TimeStampSchema(BaseModel):
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: Optional[datetime] = None


class UserStampSchema(BaseModel):
    created_by_user_id: Optional[int] = None
    updated_by_user_id: Optional[int] = None
    deleted_by_user_id: Optional[int] = None


class TimeUserStampSchema(TimeStampSchema, UserStampSchema):
    pass
