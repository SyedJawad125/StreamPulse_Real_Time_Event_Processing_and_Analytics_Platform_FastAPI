import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.permissions import USERS_MANAGE, USERS_READ
from app.dependencies import get_db, get_settings_dep, require_permissions
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserOut, UserRolesUpdate, UserUpdate
from app.services import user_service
from app.services.auth_service import CurrentUser

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=Page[UserOut])
async def list_users(
    q: str | None = Query(None, max_length=100, description="Search username/email"),
    is_active: bool | None = None, role: str | None = Query(None, max_length=50),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    _: CurrentUser = Depends(require_permissions(USERS_READ)), session: AsyncSession = Depends(get_db),
) -> Page[UserOut]:
    items, total = await user_service.list_users(session, q=q, is_active=is_active, role_code=role, limit=limit, offset=offset)
    return Page(items=[UserOut.model_validate(u) for u in items], total=total, limit=limit, offset=offset)


@router.post("", response_model=UserOut, status_code=201, summary="Create a user (admin only; there is no public sign-up)")
async def create_user(
    body: UserCreate, request: Request, current: CurrentUser = Depends(require_permissions(USERS_MANAGE)),
    session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep),
) -> UserOut:
    user = await user_service.create_user(session, settings, request, current.user, body)
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, _: CurrentUser = Depends(require_permissions(USERS_READ)),
                   session: AsyncSession = Depends(get_db)) -> UserOut:
    return UserOut.model_validate(await user_service.get_user(session, user_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request,
                      current: CurrentUser = Depends(require_permissions(USERS_MANAGE)),
                      session: AsyncSession = Depends(get_db)) -> UserOut:
    return UserOut.model_validate(await user_service.update_user(session, request, current.user, user_id, body))


@router.post("/{user_id}/activate", response_model=UserOut)
async def activate_user(user_id: uuid.UUID, request: Request,
                        current: CurrentUser = Depends(require_permissions(USERS_MANAGE)),
                        session: AsyncSession = Depends(get_db)) -> UserOut:
    return UserOut.model_validate(await user_service.set_active(session, request, current.user, user_id, True))


@router.post("/{user_id}/deactivate", response_model=UserOut,
             summary="Deactivate a user; their tokens stop working immediately")
async def deactivate_user(user_id: uuid.UUID, request: Request,
                          current: CurrentUser = Depends(require_permissions(USERS_MANAGE)),
                          session: AsyncSession = Depends(get_db)) -> UserOut:
    return UserOut.model_validate(await user_service.set_active(session, request, current.user, user_id, False))


@router.put("/{user_id}/roles", response_model=UserOut, summary="Replace the user's roles")
async def set_roles(user_id: uuid.UUID, body: UserRolesUpdate, request: Request,
                    current: CurrentUser = Depends(require_permissions(USERS_MANAGE)),
                    session: AsyncSession = Depends(get_db)) -> UserOut:
    return UserOut.model_validate(await user_service.set_roles(session, request, current.user, user_id, body.role_codes))
