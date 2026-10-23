from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.dependencies import get_current_user, get_db, get_limiter, get_settings_dep
from app.schemas.auth import (
    ChangePasswordRequest,
    CurrentUserResponse,
    LoginRequest,
    StreamTicketResponse,
    TokenResponse,
)
from app.schemas.common import Message
from app.schemas.user import UserOut
from app.services import auth_service
from app.services.auth_service import CurrentUser

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _token_response(token, expires, user) -> TokenResponse:
    return TokenResponse(access_token=token, expires_at=expires, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse, summary="Log in with username/email + password")
async def login(
    body: LoginRequest, request: Request, session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep), limiter: SlidingWindowRateLimiter = Depends(get_limiter),
) -> TokenResponse:
    token, expires, user = await auth_service.login(session, settings, limiter, request, body.username, body.password)
    return _token_response(token, expires, user)


@router.post("/token", response_model=TokenResponse, include_in_schema=True,
             summary="OAuth2 password flow (used by the Swagger 'Authorize' button)")
async def token(
    request: Request, form: OAuth2PasswordRequestForm = Depends(), session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep), limiter: SlidingWindowRateLimiter = Depends(get_limiter),
) -> TokenResponse:
    tok, expires, user = await auth_service.login(session, settings, limiter, request, form.username, form.password)
    return _token_response(tok, expires, user)


@router.post("/logout", response_model=Message, summary="Revoke the current access token")
async def logout(request: Request, current: CurrentUser = Depends(get_current_user),
                 session: AsyncSession = Depends(get_db)) -> Message:
    await auth_service.logout(session, request, current)
    return Message(message="Logged out")


@router.get("/me", response_model=CurrentUserResponse, summary="Current user and effective permissions")
async def me(current: CurrentUser = Depends(get_current_user)) -> CurrentUserResponse:
    base = UserOut.model_validate(current.user).model_dump()
    return CurrentUserResponse(**base, permissions=sorted(current.permissions))


@router.post("/change-password", response_model=TokenResponse,
             summary="Change password; all older tokens are invalidated and a fresh one is returned")
async def change_password(
    body: ChangePasswordRequest, request: Request, current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep),
) -> TokenResponse:
    tok, expires = await auth_service.change_password(
        session, settings, request, current.user, body.current_password, body.new_password)
    return _token_response(tok, expires, current.user)
