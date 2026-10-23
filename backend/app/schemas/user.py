import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")


def validate_password_strength(v: str, min_length: int = 12) -> str:
    if len(v) < min_length:
        raise ValueError(f"Password must be at least {min_length} characters")
    if len(v) > 128:
        raise ValueError("Password must be at most 128 characters")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("Password must contain at least one letter and one digit")
    return v


class RoleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code_name: str
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    username: str
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    is_active: bool
    is_verified: bool
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleSummary] = []


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    is_verified: bool = False
    role_codes: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3-50 chars: lowercase letters, digits, '.', '_' or '-'")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return validate_password_strength(v)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    is_verified: bool | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return v.lower() if v else v


class UserRolesUpdate(BaseModel):
    role_codes: list[str] = Field(max_length=20)
