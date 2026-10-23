from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.user import UserOut, validate_password_strength


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255, description="Username or email")
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strong(cls, v: str) -> str:
        return validate_password_strength(v)


class CurrentUserResponse(UserOut):
    permissions: list[str]


class StreamTicketResponse(BaseModel):
    ticket: str
    expires_in_seconds: int
