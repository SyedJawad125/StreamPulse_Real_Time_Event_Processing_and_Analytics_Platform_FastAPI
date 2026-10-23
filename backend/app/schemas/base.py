# app/schemas/base.py
"""Base schemas for common fields"""
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class TimeStampSchema(BaseModel):
    """Schema for timestamp fields"""
    created_at: datetime
    updated_at: datetime
    deleted: bool
    deleted_at: Optional[datetime] = None


class UserStampSchema(BaseModel):
    """Schema for user tracking fields"""
    created_by_user_id: Optional[int] = None
    updated_by_user_id: Optional[int] = None
    deleted_by_user_id: Optional[int] = None


class TimeUserStampSchema(TimeStampSchema, UserStampSchema):
    """Combined schema for both timestamps and user stamps"""
    pass