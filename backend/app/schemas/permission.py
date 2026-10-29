# app/schemas/permission.py
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import TimeUserStampSchema


class PermissionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1, max_length=50)
    module_name: Optional[str] = Field(None, max_length=50)


class PermissionCreate(PermissionBase):
    model_config = ConfigDict(extra="forbid")


class PermissionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, min_length=1)
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    module_name: Optional[str] = Field(None, max_length=50)
    model_config = ConfigDict(extra="forbid")


class PermissionOut(PermissionBase, TimeUserStampSchema):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RoleBasicForPermission(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class PermissionWithRoles(PermissionOut):
    roles: List[RoleBasicForPermission] = []


class PaginatedPermissions(BaseModel):
    count: int
    data: List[PermissionOut]


class PermissionListResponse(BaseModel):
    status: str
    result: PaginatedPermissions


class PaginatedPermissionsWithRoles(BaseModel):
    count: int
    data: List[PermissionWithRoles]


class PermissionListWithRolesResponse(BaseModel):
    status: str
    result: PaginatedPermissionsWithRoles
