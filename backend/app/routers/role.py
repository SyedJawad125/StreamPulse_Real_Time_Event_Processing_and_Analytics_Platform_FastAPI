# app/routers/role.py
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app import database, models, oauth2, schemas
from app.crud import audit
from app.dependencies.permission import ensure_can_grant, require
from app.exceptions import AppError
from app.utils import filter_roles

router = APIRouter(prefix="/api/roles", tags=["Roles"])

PROTECTED_ROLE_CODE = "su"  # the Super role: always holds every permission and cannot be edited/removed


def _active_role(db: Session, role_id: int) -> models.Role:
    role = db.query(models.Role).filter(models.Role.id == role_id, models.Role.deleted == False).first()  # noqa: E712
    if not role:
        raise AppError(404, f"Role with id {role_id} not found")
    return role


def _permissions_by_ids(db: Session, ids: list[int]) -> list[models.Permission]:
    ids = list(dict.fromkeys(ids))
    perms = db.query(models.Permission).filter(models.Permission.id.in_(ids), models.Permission.deleted == False).all()  # noqa: E712
    if len(perms) != len(ids):
        raise AppError(400, "One or more permission IDs are invalid or deleted", "INVALID_PERMISSION_IDS")
    return perms


@router.get("/v1/role/", response_model=schemas.RoleListWithPermissionsResponse, dependencies=[require("read_role")])
def get_roles(request: Request, skip: int = 0, limit: int = 10, include_deleted: bool = False,
              db: Session = Depends(database.get_db)):
    """Roles with pagination and filters (`name`, `code`, `description`, `search`) - includes permissions."""
    query = models.Role.get_all_including_deleted(db) if include_deleted else models.Role.get_active(db)
    query = filter_roles(request.query_params, query).order_by(models.Role.id)
    total = query.count()
    roles = query.offset(skip).limit(min(limit, 200)).all()
    return {"status": "success",
            "result": {"count": total, "data": [schemas.RoleWithPermissions.model_validate(r) for r in roles]}}


@router.get("/v1/role/{id}", response_model=schemas.RoleWithPermissions, dependencies=[require("read_role")])
def get_role(id: int, db: Session = Depends(database.get_db)):
    return _active_role(db, id)


@router.post("/v1/role/", status_code=status.HTTP_201_CREATED, response_model=schemas.RoleWithPermissions)
def create_role(role: schemas.RoleCreate, request: Request, db: Session = Depends(database.get_db),
                current_user: models.User = require("create_role")):
    if role.code and db.query(models.Role.id).filter(models.Role.code == role.code).first():
        raise AppError(400, f"Role with code '{role.code}' already exists", "ROLE_EXISTS")
    permissions = _permissions_by_ids(db, role.permission_ids or [])
    ensure_can_grant(current_user, [p.code for p in permissions])

    new_role = models.Role(**role.model_dump(exclude={"permission_ids"}), created_by_user_id=current_user.id)
    new_role.permissions = permissions
    db.add(new_role)
    db.flush()
    audit.record(db, action="role.created", actor=current_user, request=request, target_type="role",
                 target_id=new_role.id, details={"code": new_role.code, "permissions": [p.code for p in permissions]})
    db.commit()
    db.refresh(new_role)
    return new_role


@router.patch("/v1/role/{id}", response_model=schemas.RoleWithPermissions)
def update_role(id: int, role_update: schemas.RoleUpdate, request: Request, db: Session = Depends(database.get_db),
                current_user: models.User = require("update_role")):
    role = _active_role(db, id)
    data = role_update.model_dump(exclude_unset=True)
    if role.code == PROTECTED_ROLE_CODE and ("code" in data or data.get("permission_ids") is not None):
        raise AppError(403, "The Super role's code and permissions cannot be changed", "PROTECTED_ROLE")
    if data.get("code") and data["code"] != role.code and db.query(models.Role.id).filter(
            models.Role.code == data["code"], models.Role.id != id).first():
        raise AppError(400, f"Role with code '{data['code']}' already exists", "ROLE_EXISTS")

    for key in ("name", "description", "code"):
        if key in data and data[key] is not None:
            setattr(role, key, data[key])
    if data.get("permission_ids") is not None:
        permissions = _permissions_by_ids(db, data["permission_ids"])
        ensure_can_grant(current_user, [p.code for p in permissions])
        role.permissions = permissions
    role.updated_by_user_id = current_user.id
    audit.record(db, action="role.updated", actor=current_user, request=request, target_type="role", target_id=id,
                 details={"fields": sorted(data)})
    db.commit()
    db.refresh(role)
    return role


@router.delete("/v1/role/{id}", status_code=status.HTTP_200_OK)
def delete_role(id: int, request: Request, permanent: bool = False, db: Session = Depends(database.get_db),
                current_user: models.User = require("delete_role")):
    """Soft delete a role (permanent delete: superusers only). Roles still assigned to active users are protected."""
    if permanent and not current_user.is_superuser:
        raise AppError(403, "Only superusers can permanently delete roles", "SUPERUSER_ONLY")
    role = db.query(models.Role).filter(models.Role.id == id).first()
    if not role:
        raise AppError(404, f"Role with id {id} not found")
    if role.code == PROTECTED_ROLE_CODE:
        raise AppError(403, "The Super role cannot be deleted", "PROTECTED_ROLE")
    in_use = db.query(models.User).filter(models.User.role_id == id, models.User.deleted == False).count()  # noqa: E712
    if in_use:
        raise AppError(400, f"Cannot delete role. It is assigned to {in_use} active user(s).", "ROLE_IN_USE")

    audit.record(db, action="role.deleted", actor=current_user, request=request, target_type="role", target_id=id,
                 details={"code": role.code, "permanent": permanent})
    if permanent:
        db.delete(role)
        db.commit()
        return {"message": "Role permanently deleted"}
    role.soft_delete(user_id=current_user.id)
    db.commit()
    return {"message": "Role soft deleted successfully"}


@router.post("/v1/role/{id}/restore", response_model=schemas.RoleWithPermissions)
def restore_role(id: int, request: Request, db: Session = Depends(database.get_db),
                 current_user: models.User = require("update_role")):
    role = db.query(models.Role).filter(models.Role.id == id, models.Role.deleted == True).first()  # noqa: E712
    if not role:
        raise AppError(404, f"Deleted role with id {id} not found")
    role.restore()
    role.updated_by_user_id = current_user.id
    audit.record(db, action="role.restored", actor=current_user, request=request, target_type="role", target_id=id)
    db.commit()
    db.refresh(role)
    return role


@router.post("/v1/role/{role_id}/permissions/{permission_id}", response_model=schemas.RoleWithPermissions)
def add_permission_to_role(role_id: int, permission_id: int, request: Request, db: Session = Depends(database.get_db),
                           current_user: models.User = require("update_role")):
    role = _active_role(db, role_id)
    if role.code == PROTECTED_ROLE_CODE:
        raise AppError(403, "The Super role's permissions cannot be changed", "PROTECTED_ROLE")
    perm = db.query(models.Permission).filter(models.Permission.id == permission_id,
                                              models.Permission.deleted == False).first()  # noqa: E712
    if not perm:
        raise AppError(404, f"Permission with id {permission_id} not found")
    ensure_can_grant(current_user, [perm.code])
    if perm not in role.permissions:
        role.permissions.append(perm)
        role.updated_by_user_id = current_user.id
        audit.record(db, action="role.permission_added", actor=current_user, request=request, target_type="role",
                     target_id=role_id, details={"permission": perm.code})
        db.commit()
        db.refresh(role)
    return role


@router.delete("/v1/role/{role_id}/permissions/{permission_id}", response_model=schemas.RoleWithPermissions)
def remove_permission_from_role(role_id: int, permission_id: int, request: Request,
                                db: Session = Depends(database.get_db), current_user: models.User = require("update_role")):
    role = _active_role(db, role_id)
    if role.code == PROTECTED_ROLE_CODE:
        raise AppError(403, "The Super role's permissions cannot be changed", "PROTECTED_ROLE")
    perm = db.query(models.Permission).filter(models.Permission.id == permission_id).first()
    if perm and perm in role.permissions:
        role.permissions.remove(perm)
        role.updated_by_user_id = current_user.id
        audit.record(db, action="role.permission_removed", actor=current_user, request=request, target_type="role",
                     target_id=role_id, details={"permission": perm.code})
        db.commit()
        db.refresh(role)
    return role
