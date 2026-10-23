from fastapi import APIRouter

from app.api.v1 import admin, analytics, api_keys, auth, events, permissions, roles, users

api_router = APIRouter()
for module in (auth, users, roles, permissions, api_keys, events, analytics, admin):
    api_router.include_router(module.router)
