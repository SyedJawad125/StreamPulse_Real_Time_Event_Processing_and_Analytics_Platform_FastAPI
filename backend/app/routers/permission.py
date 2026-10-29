# app/routers/permission.py
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session, joinedload

from app import database, models, schemas
from app.crud import audit
from app.dependencies.permission import require
from app.exceptions import AppError
from app.utils import filter_permissions

router = APIRouter(prefix="/api/permissions", tags=["Permissions"])


@router.get("/v1/permission/", response_model=schemas.PermissionListResponse, dependencies=[require("read_permission")])
def get_permissions(request: Request, skip: int = 0, limit: int = 10, include_deleted: bool = False,
                    db: Session = Depends(database.get_db)):
    """Permissions with pagination and filters (`name`, `code`, `module_name`, `description`, `search`)."""
    query = models.Permission.get_all_including_deleted(db) if include_deleted else models.Permission.get_active(db)
    query = filter_permissions(request.query_params, query).order_by(models.Permission.module_name, models.Permission.code)
    total = query.count()
    permissions = query.offset(skip).limit(min(limit, 500)).all()
    return {"status": "success",
            "result": {"count": total, "data": [schemas.PermissionOut.model_validate(p) for p in permissions]}}


@router.get("/v1/permission/{id}", response_model=schemas.PermissionOut, dependencies=[require("read_permission")])
def get_permission(id: int, db: Session = Depends(database.get_db)):
    permission = db.query(models.Permission).filter(models.Permission.id == id,
                                                    models.Permission.deleted == False).first()  # noqa: E712
    if not permission:
        raise AppError(404, f"Permission with id {id} not found")
    return permission


@router.get("/v1/permission/{id}/with-roles", response_model=schemas.PermissionWithRoles,
            dependencies=[require("read_permission")])
def get_permission_with_roles(id: int, db: Session = Depends(database.get_db)):
    """Permission plus every role that holds it."""
    permission = (db.query(models.Permission).options(joinedload(models.Permission.roles))
                  .filter(models.Permission.id == id, models.Permission.deleted == False).first())  # noqa: E712
    if not permission:
        raise AppError(404, f"Permission with id {id} not found")
    return permission


@router.post("/v1/permission/", status_code=status.HTTP_201_CREATED, response_model=schemas.PermissionOut)
def create_permission(permission: schemas.PermissionCreate, request: Request, db: Session = Depends(database.get_db),
                      current_user: models.User = require("create_permission")):
    if db.query(models.Permission.id).filter(models.Permission.code == permission.code).first():
        raise AppError(400, f"Permission with code '{permission.code}' already exists", "PERMISSION_EXISTS")
    new_permission = models.Permission(**permission.model_dump(), created_by_user_id=current_user.id)
    db.add(new_permission)
    db.flush()
    audit.record(db, action="permission.created", actor=current_user, request=request, target_type="permission",
                 target_id=new_permission.id, details={"code": new_permission.code})
    db.commit()
    db.refresh(new_permission)
    return new_permission


@router.patch("/v1/permission/{id}", response_model=schemas.PermissionOut)
def update_permission(id: int, permission_update: schemas.PermissionUpdate, request: Request,
                      db: Session = Depends(database.get_db), current_user: models.User = require("update_permission")):
    permission = db.query(models.Permission).filter(models.Permission.id == id,
                                                    models.Permission.deleted == False).first()  # noqa: E712
    if not permission:
        raise AppError(404, f"Permission with id {id} not found")
    data = permission_update.model_dump(exclude_unset=True)
    if data.get("code") and data["code"] != permission.code:
        if db.query(models.Permission.id).filter(models.Permission.code == data["code"],
                                                 models.Permission.id != id).first():
            raise AppError(400, f"Permission with code '{data['code']}' already exists", "PERMISSION_EXISTS")
    for key, value in data.items():
        if value is not None or key == "module_name":
            setattr(permission, key, value)
    permission.updated_by_user_id = current_user.id
    audit.record(db, action="permission.updated", actor=current_user, request=request, target_type="permission",
                 target_id=id, details={"fields": sorted(data)})
    db.commit()
    db.refresh(permission)
    return permission


@router.delete("/v1/permission/{id}", status_code=status.HTTP_200_OK)
def delete_permission(id: int, request: Request, permanent: bool = False, db: Session = Depends(database.get_db),
                      current_user: models.User = require("delete_permission")):
    """Soft delete a permission (permanent delete: superusers only). Permissions still in use are protected."""
    if permanent and not current_user.is_superuser:
        raise AppError(403, "Only superusers can permanently delete permissions", "SUPERUSER_ONLY")
    permission = (db.query(models.Permission).options(joinedload(models.Permission.roles))
                  .filter(models.Permission.id == id).first())
    if not permission:
        raise AppError(404, f"Permission with id {id} not found")
    active_roles = [r for r in permission.roles if not r.deleted]
    if active_roles:
        raise AppError(400, "Cannot delete permission. It is assigned to role(s): "
                            + ", ".join(r.name for r in active_roles), "PERMISSION_IN_USE")
    active_users = [u for u in permission.users if not u.deleted]
    if active_users:
        raise AppError(400, f"Cannot delete permission. It is directly assigned to {len(active_users)} user(s).",
                       "PERMISSION_IN_USE")
    audit.record(db, action="permission.deleted", actor=current_user, request=request, target_type="permission",
                 target_id=id, details={"code": permission.code, "permanent": permanent})
    if permanent:
        db.delete(permission)  # ON DELETE CASCADE clears the association rows
        db.commit()
        return {"message": "Permission permanently deleted"}
    permission.soft_delete(user_id=current_user.id)
    db.commit()
    return {"message": "Permission soft deleted successfully"}


@router.post("/v1/permission/{id}/restore", response_model=schemas.PermissionOut)
def restore_permission(id: int, request: Request, db: Session = Depends(database.get_db),
                       current_user: models.User = require("update_permission")):
    permission = db.query(models.Permission).filter(models.Permission.id == id,
                                                    models.Permission.deleted == True).first()  # noqa: E712
    if not permission:
        raise AppError(404, f"Deleted permission with id {id} not found")
    permission.restore()
    permission.updated_by_user_id = current_user.id
    audit.record(db, action="permission.restored", actor=current_user, request=request, target_type="permission",
                 target_id=id)
    db.commit()
    db.refresh(permission)
    return permission
