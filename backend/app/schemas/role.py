import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    code_name: str
    module_name: str
    description: str | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    code_name: str
    description: str | None = None
    is_system: bool
    permissions: list[PermissionOut] = []
    created_at: datetime
    updated_at: datetime


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    code_name: str = Field(min_length=2, max_length=50)
    description: str | None = Field(default=None, max_length=255)

    @field_validator("code_name")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9_]{1,49}$", v):
            raise ValueError("code_name must be UPPER_SNAKE_CASE")
        return v


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=255)


class RolePermissionsUpdate(BaseModel):
    permission_codes: list[str] = Field(max_length=100)
