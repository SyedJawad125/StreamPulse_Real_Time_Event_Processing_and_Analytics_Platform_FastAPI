# app/routers/user.py
from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import database, models, oauth2, schemas, utils
from app.crud import audit
from app.crud import auth as auth_crud
from app.database import get_db
from app.dependencies.permission import ensure_can_grant, has_permission, require
from app.exceptions import AppError

router = APIRouter(prefix="/api/user", tags=["Users"])


# ----------------------------------------------------------------------------- helpers
def _role_or_404(db: Session, role_id: int) -> models.Role:
    role = db.query(models.Role).filter(models.Role.id == role_id, models.Role.deleted == False).first()  # noqa: E712
    if not role:
        raise AppError(404, "Role not found")
    return role


def _other_active_superusers(db: Session, exclude_id: int) -> int:
    return db.query(func.count(models.User.id)).filter(
        models.User.is_superuser == True, models.User.is_active == True,  # noqa: E712
        models.User.deleted == False, models.User.id != exclude_id).scalar() or 0


def _ensure_not_last_superuser(db: Session, target: models.User) -> None:
    if target.is_superuser and target.is_active and not _other_active_superusers(db, target.id):
        raise AppError(409, "This would leave the system without an active superuser", "LAST_SUPERUSER")


def _login_payload(db: Session, user: models.User, message: str = "Login successful") -> dict:
    permissions = oauth2.build_permissions_dict(db, user)
    if not user.is_superuser and not user.role and not any(permissions.values()):
        raise AppError(403, "User has no role assigned", "NO_ROLE_ASSIGNED")
    access_token, refresh_token = auth_crud.issue_tokens(user)
    return {
        "message": message,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_superuser": bool(user.is_superuser),
            "role_id": user.role.id if user.role else None,
            "role_name": user.role.name if user.role else None,
        },
        "permissions": permissions,
    }


# ----------------------------------------------------------------------------- create / auth
@router.post("/v1/signup/", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(user: schemas.UserCreate, request: Request, db: Session = Depends(get_db),
                current_user: models.User = require("create_user")):
    """Create a user. (Not public: the caller needs `create_user`; only superusers can create superusers.)"""
    if user.is_superuser and not current_user.is_superuser:
        raise AppError(403, "Only superusers can create superusers", "SUPERUSER_ONLY")

    # Includes soft-deleted users so e-mails are never silently recycled.
    existing = db.query(models.User).filter(func.lower(models.User.email) == user.email.lower()).first()
    if existing and not existing.deleted:
        raise AppError(400, "Email already registered", "EMAIL_EXISTS")
    if existing and existing.deleted:
        raise AppError(400, "This email was previously registered. Please contact support.", "EMAIL_DELETED")

    role = None
    if user.role_id is not None:
        role = _role_or_404(db, user.role_id)
        ensure_can_grant(current_user, [p.code for p in role.permissions])
        if role.code == "su" and not current_user.is_superuser:
            raise AppError(403, "Only superusers can assign the Super role", "SUPERUSER_ONLY")
    elif not user.is_superuser:
        raise AppError(400, "role_id is required for non-superusers", "ROLE_REQUIRED")

    new_user = models.User(username=user.username, email=user.email, hashed_password=utils.get_password_hash(user.password),
                           is_active=True, is_superuser=bool(user.is_superuser), role_id=role.id if role else None)
    db.add(new_user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AppError(400, "Email already registered", "EMAIL_EXISTS") from None
    audit.record(db, action="user.created", actor=current_user, request=request, target_type="user",
                 target_id=new_user.id, details={"email": new_user.email, "role_id": new_user.role_id,
                                                 "is_superuser": new_user.is_superuser})
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/v1/login/")
def login(user_credentials: schemas.LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Log in with email + password (throttled; accounts lock after repeated failures)."""
    user = auth_crud.login(db, request, request.app.state.rate_limiter, user_credentials.email, user_credentials.password)
    return _login_payload(db, user)


@router.post("/v1/token/", include_in_schema=True)
def login_form(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 password flow for the Swagger *Authorize* button (`username` = your e-mail)."""
    user = auth_crud.login(db, request, request.app.state.rate_limiter, form.username, form.password)
    return _login_payload(db, user)


@router.post("/v1/refresh/", response_model=schemas.TokenResponse)
def refresh_tokens(body: schemas.RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Exchange a refresh token for a new access + refresh pair (the old refresh token stops working)."""
    user = auth_crud.refresh(db, request, body.refresh_token)
    access_token, refresh_token = auth_crud.issue_tokens(user)
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.post("/v1/logout/")
def logout(request: Request, body: schemas.LogoutRequest | None = None, db: Session = Depends(get_db),
           current_user: models.User = Depends(oauth2.get_current_user)):
    """Revoke the current access token (and the refresh token, if supplied)."""
    auth_crud.logout(db, request, current_user, body.refresh_token if body else None)
    return {"message": "Logged out"}


@router.post("/v1/change-password/", response_model=schemas.TokenResponse)
def change_password(body: schemas.ChangePasswordRequest, request: Request, db: Session = Depends(get_db),
                    current_user: models.User = Depends(oauth2.get_current_user)):
    """Change your own password. Every older token stops working; a fresh pair is returned."""
    user = auth_crud.change_password(db, request, current_user, body.current_password, body.new_password)
    access_token, refresh_token = auth_crud.issue_tokens(user)
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@router.get("/v1/me/", response_model=schemas.UserMeOut)
def get_current_user_profile(db: Session = Depends(get_db), current_user: models.User = Depends(oauth2.get_current_user)):
    """Current logged-in user with role name and effective permissions."""
    data = schemas.UserOut.model_validate(current_user).model_dump()
    return schemas.UserMeOut(**data, role_name=current_user.role.name if current_user.role else None,
                             permissions=oauth2.build_permissions_dict(db, current_user))


# ----------------------------------------------------------------------------- list / read
@router.get("/v1/all/users/", response_model=schemas.UserListResponse, dependencies=[require("read_user")])
def get_all_users(request: Request, skip: int = 0, limit: int = 10, include_deleted: bool = False,
                  db: Session = Depends(get_db)):
    """All users with pagination and filters (`email`, `username`, `role_id`, `search`)."""
    query = models.User.get_all_including_deleted(db) if include_deleted else models.User.get_active(db)
    query = utils.filter_users(request.query_params, query).order_by(models.User.id)
    total = query.count()
    users = query.offset(skip).limit(min(limit, 200)).all()
    return {"status": "success", "result": {"count": total, "data": users}}


@router.get("/{id}", response_model=schemas.UserOut)
def get_user(id: int, db: Session = Depends(get_db), current_user: models.User = Depends(oauth2.get_current_user)):
    """Users can view themselves; viewing others needs `read_user`."""
    if current_user.id != id and not has_permission(current_user, "read_user"):
        raise AppError(403, "Not authorized to access this user's information", "PERMISSION_DENIED")
    user = db.query(models.User).filter(models.User.id == id, models.User.deleted == False).first()  # noqa: E712
    if not user:
        raise AppError(404, f"User with id {id} not found")
    return user


# ----------------------------------------------------------------------------- update / delete
@router.patch("/{id}", response_model=schemas.UserOut)
def update_user(id: int, user_update: schemas.UserUpdate, request: Request, db: Session = Depends(get_db),
                current_user: models.User = Depends(oauth2.get_current_user)):
    """Update a user.

    * Anyone: their OWN username/email (password: use /v1/change-password/).
    * `update_user`: other users' username/email/password/role.   * `toggle_user`: is_active.
    * `is_superuser`: superusers only.
    """
    is_self = current_user.id == id
    can_update = has_permission(current_user, "update_user")
    if not (is_self or can_update):
        raise AppError(403, "Not authorized to update this user's information", "PERMISSION_DENIED")

    user = db.query(models.User).filter(models.User.id == id, models.User.deleted == False).first()  # noqa: E712
    if not user:
        raise AppError(404, f"User with id {id} not found")

    changes = user_update.model_dump(exclude_unset=True)
    if "role_id" in changes and not can_update:
        raise AppError(403, "Changing a role needs the update_user permission", "PERMISSION_DENIED")
    if "is_active" in changes and not has_permission(current_user, "toggle_user"):
        raise AppError(403, "Changing is_active needs the toggle_user permission", "PERMISSION_DENIED")
    if "is_superuser" in changes and not current_user.is_superuser:
        raise AppError(403, "Only superusers can change is_superuser", "SUPERUSER_ONLY")
    if "password" in changes and is_self:
        raise AppError(403, "Use /api/user/v1/change-password/ to change your own password", "USE_CHANGE_PASSWORD")

    if changes.get("email") and changes["email"] != user.email:
        if db.query(models.User.id).filter(func.lower(models.User.email) == changes["email"].lower(),
                                           models.User.id != id).first():
            raise AppError(400, "Email already registered", "EMAIL_EXISTS")
    if changes.get("role_id") is not None:
        role = _role_or_404(db, changes["role_id"])
        ensure_can_grant(current_user, [p.code for p in role.permissions])
        if role.code == "su" and not current_user.is_superuser:
            raise AppError(403, "Only superusers can assign the Super role", "SUPERUSER_ONLY")
    if changes.get("is_active") is False:
        if is_self:
            raise AppError(400, "You cannot deactivate your own account", "SELF_DEACTIVATION")
        _ensure_not_last_superuser(db, user)
    if changes.get("is_superuser") is False:
        _ensure_not_last_superuser(db, user)

    if "password" in changes:  # admin reset: old sessions of that user end
        user.hashed_password = utils.get_password_hash(changes.pop("password"))
        user.token_version += 1
    for field, value in changes.items():
        if value is None and field in ("email", "is_active", "is_superuser"):
            continue
        setattr(user, field, value)

    audit.record(db, action="user.updated", actor=current_user, request=request, target_type="user", target_id=id,
                 details={"fields": sorted(user_update.model_dump(exclude_unset=True))})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(400, "Email already registered", "EMAIL_EXISTS") from None
    db.refresh(user)
    return user


@router.delete("/{id}", status_code=status.HTTP_200_OK, dependencies=[require("delete_user")])
def delete_user(id: int, request: Request, permanent: bool = False, db: Session = Depends(get_db),
                current_user: models.User = Depends(oauth2.get_current_user)):
    """Soft delete a user (permanent delete: superusers only)."""
    if permanent and not current_user.is_superuser:
        raise AppError(403, "Only superusers can permanently delete users", "SUPERUSER_ONLY")
    user = db.query(models.User).filter(models.User.id == id).first()
    if not user:
        raise AppError(404, f"User with id {id} not found")
    if user.id == current_user.id:
        raise AppError(400, "Cannot delete your own account", "SELF_DELETE")
    _ensure_not_last_superuser(db, user)

    audit.record(db, action="user.deleted", actor=current_user, request=request, target_type="user", target_id=id,
                 details={"permanent": permanent, "email": user.email})
    if permanent:
        try:
            db.delete(user)
            db.commit()
        except IntegrityError:
            db.rollback()
            raise AppError(409, "User is referenced by other records; soft delete instead", "USER_IN_USE") from None
        return {"message": "User permanently deleted"}
    user.soft_delete()
    user.token_version += 1
    db.commit()
    return {"message": "User soft deleted successfully"}


@router.post("/{id}/restore", response_model=schemas.UserOut, dependencies=[require("delete_user")])
def restore_user(id: int, request: Request, db: Session = Depends(get_db),
                 current_user: models.User = Depends(oauth2.get_current_user)):
    """Restore a soft-deleted user."""
    user = db.query(models.User).filter(models.User.id == id, models.User.deleted == True).first()  # noqa: E712
    if not user:
        raise AppError(404, f"Deleted user with id {id} not found")
    user.restore()
    audit.record(db, action="user.restored", actor=current_user, request=request, target_type="user", target_id=id)
    db.commit()
    db.refresh(user)
    return user


# ----------------------------------------------------------------------------- direct permissions
@router.post("/{id}/permissions/{permission_id}", response_model=schemas.UserDetailed)
def grant_permission_to_user(id: int, permission_id: int, request: Request, db: Session = Depends(get_db),
                             current_user: models.User = require("update_user")):
    """Grant a permission directly to a user (on top of their role)."""
    user = db.query(models.User).filter(models.User.id == id, models.User.deleted == False).first()  # noqa: E712
    perm = db.query(models.Permission).filter(models.Permission.id == permission_id,
                                              models.Permission.deleted == False).first()  # noqa: E712
    if not user or not perm:
        raise AppError(404, "User or permission not found")
    ensure_can_grant(current_user, [perm.code])
    if perm not in user.permissions:
        user.permissions.append(perm)
        audit.record(db, action="user.permission_granted", actor=current_user, request=request, target_type="user",
                     target_id=id, details={"permission": perm.code})
        db.commit()
        db.refresh(user)
    return user


@router.delete("/{id}/permissions/{permission_id}", response_model=schemas.UserDetailed)
def revoke_permission_from_user(id: int, permission_id: int, request: Request, db: Session = Depends(get_db),
                                current_user: models.User = require("update_user")):
    user = db.query(models.User).filter(models.User.id == id, models.User.deleted == False).first()  # noqa: E712
    perm = db.query(models.Permission).filter(models.Permission.id == permission_id).first()
    if not user:
        raise AppError(404, f"User with id {id} not found")
    if perm and perm in user.permissions:
        user.permissions.remove(perm)
        audit.record(db, action="user.permission_revoked", actor=current_user, request=request, target_type="user",
                     target_id=id, details={"permission": perm.code})
        db.commit()
        db.refresh(user)
    return user
