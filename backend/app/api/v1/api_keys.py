import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.permissions import API_KEYS_MANAGE, API_KEYS_READ
from app.dependencies import get_db, get_settings_dep, require_permissions
from app.schemas.api_key import APIKeyCreate, APIKeyCreated, APIKeyOut, APIKeyUpdate
from app.schemas.common import Page
from app.services import api_key_service
from app.services.auth_service import CurrentUser

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


@router.post("", response_model=APIKeyCreated, status_code=201,
             summary="Create an API key. The plaintext `key` is returned ONLY in this response.")
async def create_api_key(body: APIKeyCreate, request: Request,
                         current: CurrentUser = Depends(require_permissions(API_KEYS_MANAGE)),
                         session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep)) -> APIKeyCreated:
    key, plaintext = await api_key_service.create_api_key(session, settings, request, current.user, body)
    return APIKeyCreated(**APIKeyOut.model_validate(key).model_dump(), key=plaintext)


@router.get("", response_model=Page[APIKeyOut])
async def list_api_keys(is_active: bool | None = None, customer_id: str | None = Query(None, max_length=100),
                        limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        _: CurrentUser = Depends(require_permissions(API_KEYS_READ)),
                        session: AsyncSession = Depends(get_db)) -> Page[APIKeyOut]:
    items, total = await api_key_service.list_api_keys(session, is_active=is_active, customer_id=customer_id,
                                                       limit=limit, offset=offset)
    return Page(items=[APIKeyOut.model_validate(k) for k in items], total=total, limit=limit, offset=offset)


@router.get("/{key_id}", response_model=APIKeyOut)
async def get_api_key(key_id: uuid.UUID, _: CurrentUser = Depends(require_permissions(API_KEYS_READ)),
                      session: AsyncSession = Depends(get_db)) -> APIKeyOut:
    return APIKeyOut.model_validate(await api_key_service.get_api_key(session, key_id))


@router.patch("/{key_id}", response_model=APIKeyOut)
async def update_api_key(key_id: uuid.UUID, body: APIKeyUpdate, request: Request,
                         current: CurrentUser = Depends(require_permissions(API_KEYS_MANAGE)),
                         session: AsyncSession = Depends(get_db)) -> APIKeyOut:
    return APIKeyOut.model_validate(await api_key_service.update_api_key(session, request, current.user, key_id, body))


@router.post("/{key_id}/revoke", response_model=APIKeyOut, summary="Revoke a key (irreversible)")
async def revoke_api_key(key_id: uuid.UUID, request: Request,
                         current: CurrentUser = Depends(require_permissions(API_KEYS_MANAGE)),
                         session: AsyncSession = Depends(get_db)) -> APIKeyOut:
    return APIKeyOut.model_validate(await api_key_service.revoke_api_key(session, request, current.user, key_id))
