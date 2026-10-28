# app/dependencies/permission.py
"""Server-side permission checks. Usage:  @router.get(..., dependencies=[require("read_role")])"""
from fastapi import Depends

from app import models, oauth2
from app.exceptions import AppError


def _denied(codes: tuple[str, ...]) -> AppError:
    return AppError(403, "You do not have permission to perform this action", "PERMISSION_DENIED")


def require(*codes: str):
    """Caller must hold ALL given permission codes (superusers always pass)."""

    def checker(current_user: models.User = Depends(oauth2.get_current_user)) -> models.User:
        if current_user.is_superuser:
            return current_user
        if not all(current_user.permissions_dict.get(c) for c in codes):
            raise _denied(codes)
        return current_user

    return Depends(checker)


def require_any(*codes: str):
    """Caller must hold AT LEAST ONE of the codes."""

    def checker(current_user: models.User = Depends(oauth2.get_current_user)) -> models.User:
        if current_user.is_superuser or any(current_user.permissions_dict.get(c) for c in codes):
            return current_user
        raise _denied(codes)

    return Depends(checker)


def has_permission(user: models.User, code: str) -> bool:
    return bool(user.is_superuser or user.permissions_dict.get(code))


def ensure_can_grant(actor: models.User, codes) -> None:
    """Privilege-escalation guard: you cannot hand out permissions you do not hold yourself (superusers can)."""
    if actor.is_superuser:
        return
    missing = sorted(c for c in set(codes) if not actor.permissions_dict.get(c))
    if missing:
        raise AppError(403, f"You cannot grant permissions you do not hold: {', '.join(missing)}", "CANNOT_GRANT")
