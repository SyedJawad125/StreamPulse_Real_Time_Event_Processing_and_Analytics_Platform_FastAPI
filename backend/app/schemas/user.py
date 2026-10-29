# app/schemas/user.py
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.base import TimeStampSchema
from app.utils import validate_password_strength


class UserBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None


class UserCreate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role_id: Optional[int] = None
    is_superuser: Optional[bool] = False  # only a superuser may set this (enforced in the router)
    model_config = ConfigDict(extra="forbid")

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        return validate_password_strength(v)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8)
    role_id: Optional[int] = None           # needs update_user
    is_active: Optional[bool] = None        # needs toggle_user
    is_superuser: Optional[bool] = None     # superusers only
    model_config = ConfigDict(extra="forbid")

    @field_validator("email")
    @classmethod
    def _lower_email(cls, v):
        return v.lower() if v else v

    @field_validator("password")
    @classmethod
    def _strong(cls, v):
        return validate_password_strength(v) if v is not None else v


class UserOut(UserBase, TimeStampSchema):
    id: int
    is_active: bool
    is_superuser: bool
    role_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class UserMeOut(UserOut):
    """Current user with their role name and effective permissions."""
    role_name: Optional[str] = None
    permissions: Dict[str, bool] = {}


class PaginatedUsers(BaseModel):
    count: int
    data: List[UserOut]


class UserListResponse(BaseModel):
    status: str
    result: PaginatedUsers


# ---- Auth schemas ----
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    model_config = ConfigDict(extra="forbid")

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        return validate_password_strength(v)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None
    token_type: Optional[str] = None


class StreamTicketResponse(BaseModel):
    ticket: str
    expires_in_seconds: int


# ---- Nested schemas for relationships ----
class RoleBasic(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    description: str
    model_config = ConfigDict(from_attributes=True)


class PermissionBasic(BaseModel):
    id: int
    name: str
    code: str
    module_name: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class UserWithRole(UserOut):
    role: Optional[RoleBasic] = None


class UserWithPermissions(UserOut):
    permissions: List[PermissionBasic] = []


class UserDetailed(UserOut):
    role: Optional[RoleBasic] = None
    permissions: List[PermissionBasic] = []
