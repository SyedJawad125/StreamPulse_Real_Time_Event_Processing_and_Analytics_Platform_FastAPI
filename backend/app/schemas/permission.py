# # app/schemas/permission.py

# from typing import Optional, List
# from pydantic import BaseModel

# # Shared base schema
# class PermissionBase(BaseModel):
#     name: str
#     description: str
#     code: str
#     module_name: Optional[str] = None

# # For permission creation
# class PermissionCreate(PermissionBase):
#     class Config:
#         extra = "forbid"

# # For permission update
# class PermissionUpdate(BaseModel):
#     name: Optional[str] = None
#     description: Optional[str] = None
#     code: Optional[str] = None
#     module_name: Optional[str] = None

#     class Config:
#         extra = "forbid"

# # Permission response schema
# class Permission(PermissionBase):
#     id: int

#     class Config:
#         from_attributes = True  # Pydantic v2 equivalent of orm_mode

# # Paginated permission list
# class PaginatedPermissions(BaseModel):
#     count: int
#     data: List[Permission]

# # Full API response wrapper
# class PermissionListResponse(BaseModel):
#     status: str
#     result: PaginatedPermissions




# app/schemas/permission.py
from pydantic import BaseModel, Field
from typing import Optional, List
from app.schemas.base import TimeUserStampSchema


class PermissionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1, max_length=50)
    module_name: Optional[str] = Field(None, max_length=50)


class PermissionCreate(PermissionBase):
    class Config:
        extra = "forbid"


class PermissionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = Field(None, min_length=1)
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    module_name: Optional[str] = Field(None, max_length=50)
    
    class Config:
        extra = "forbid"


class PermissionOut(PermissionBase, TimeUserStampSchema):
    id: int
    
    class Config:
        from_attributes = True


# ✅ NEW: Permission with role info
class RoleBasicForPermission(BaseModel):
    """Basic role info for nested permission responses"""
    id: int
    name: str
    code: Optional[str] = None
    
    class Config:
        from_attributes = True


class PermissionWithRoles(PermissionOut):
    """Permission with roles that have this permission"""
    roles: List[RoleBasicForPermission] = []
    
    class Config:
        from_attributes = True


class PaginatedPermissions(BaseModel):
    count: int
    data: list[PermissionOut]


class PermissionListResponse(BaseModel):
    status: str
    result: PaginatedPermissions


class PaginatedPermissionsWithRoles(BaseModel):
    count: int
    data: list[PermissionWithRoles]


class PermissionListWithRolesResponse(BaseModel):
    status: str
    result: PaginatedPermissionsWithRoles