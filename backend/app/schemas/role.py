# app/schemas/role.py
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import TimeUserStampSchema


class PermissionInRole(BaseModel):
    id: int
    name: str
    description: str
    code: str
    module_name: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=1)
    code: Optional[str] = Field(None, max_length=50)


class RoleCreate(RoleBase):
    permission_ids: Optional[List[int]] = []
    model_config = ConfigDict(extra="forbid")


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, min_length=1)
    code: Optional[str] = Field(None, max_length=50)
    permission_ids: Optional[List[int]] = None
    model_config = ConfigDict(extra="forbid")


class RoleOut(RoleBase, TimeUserStampSchema):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RoleWithPermissions(RoleOut):
    permissions: List[PermissionInRole] = []


class RoleWithStats(RoleOut):
    user_count: int = 0
    permission_count: int = 0


class PaginatedRoles(BaseModel):
    count: int
    data: List[RoleOut]


class PaginatedRolesWithPermissions(BaseModel):
    count: int
    data: List[RoleWithPermissions]


class RoleListResponse(BaseModel):
    status: str
    result: PaginatedRoles


class RoleListWithPermissionsResponse(BaseModel):
    status: str
    result: PaginatedRolesWithPermissions
