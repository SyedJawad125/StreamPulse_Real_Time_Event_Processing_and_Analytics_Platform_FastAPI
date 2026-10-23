# from fastapi import APIRouter, Depends, status, Request, HTTPException
# from sqlalchemy.orm import Session
# from typing import List, Optional, Any
# from .. import database, schemas, models, oauth2
# from app.utils import paginate_data, create_response, filter_permissions
# from fastapi.responses import JSONResponse


# router = APIRouter(
#     prefix="/permissions",
#     tags=['Permissions']
# )

# # @router.get("/", response_model=List[schemas.Department])

# # @router.get("/", response_model=Any)
# @router.get("/", response_model=schemas.PermissionListResponse)
# def get_permissions(
#     request: Request,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user),
# ):
#     try:
#         query = db.query(models.Permission)
#         query = filter_permissions(request.query_params, query)
#         data = query.all()
#         paginated_data, count = paginate_data(data, request)

#         # ✅ Convert ORM to Pydantic
#         serialized_data = [schemas.Permission.from_orm(perms) for perms in paginated_data]

#         response_data = {
#             "count": count,
#             "data": serialized_data
#         }

#         return {
#             "status": "SUCCESSFUL",
#             "result": response_data
#         }

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))




# @router.post("/", status_code=status.HTTP_201_CREATED, response_model=schemas.Permission)
# # @router.post("/", status_code=status.HTTP_201_CREATED)
# def create_permission(
#     permission: schemas.PermissionCreate,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ) -> Any:
#     try:
        

#         permission_data = permission.dict()
#         permission_data["created_by_user_id"] = current_user.id  # ✅ Correct field name

#         new_permission = models.Permission(**permission_data)
#         db.add(new_permission)
#         db.commit()
#         db.refresh(new_permission)

#         return new_permission

#     except HTTPException as he:
#         raise he
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))



# @router.get("/{id}", response_model=schemas.Permission)
# def get_permission(id: int, db: Session = Depends(database.get_db), 
#                   current_user: models.User = Depends(oauth2.get_current_user)):
#     permission = db.query(models.Permission).filter(models.Permission.id == id).first()
#     if not permission:
#         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
#                            detail=f"Permission with id {id} not found")
#     return permission

# @router.patch("/{id}", response_model=schemas.Permission)
# def patch_update_permission(
#     id: int,
#     updated_permission: schemas.PermissionUpdate,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     try:
        

#         permission_instance = db.query(models.Permission).filter(models.Permission.id == id).first()

#         if not permission_instance:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Permission with id {id} not found"
#             )

#         update_data = updated_permission.dict(exclude_unset=True)

#         for key, value in update_data.items():
#             setattr(permission_instance, key, value)

#         db.commit()
#         db.refresh(permission_instance)

#         return permission_instance

#     except HTTPException as he:
#         raise he
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"An error occurred while patching the permission: {str(e)}"
#         )


# # @router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)

# @router.delete("/{id}", status_code=status.HTTP_200_OK)
# def delete_permission(
#     id: int,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
    

#     permission_query = db.query(models.Permission).filter(models.Permission.id == id)
#     permission = permission_query.first()

#     if not permission:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Permission with id {id} not found"
#         )

#     permission_query.delete(synchronize_session=False)
#     db.commit()

#     return {"message": "Permission deleted successfully"}






# # app/api/routers/permission.py
# from fastapi import APIRouter, Depends, status, Request, HTTPException
# from sqlalchemy.orm import Session
# from typing import Optional

# from app import database, schemas, models, oauth2
# from app.utils import paginate_data, filter_permissions


# router = APIRouter(
#     prefix="/api/permissions",
#     tags=['Permissions']
# )


# @router.get("/v1/permission/", response_model=schemas.PermissionListResponse)
# def get_permissions(
#     request: Request,
#     skip: int = 0,
#     limit: int = 10,
#     include_deleted: bool = False,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user),
# ):
#     """Get all permissions with pagination and filtering"""
#     try:
#         # Query based on include_deleted flag
#         if include_deleted:
#             query = models.Permission.get_all_including_deleted(db)
#         else:
#             query = models.Permission.get_active(db)
        
#         # Apply filters
#         query = filter_permissions(request.query_params, query)
        
#         total = query.count()
#         permissions = query.offset(skip).limit(limit).all()

#         # Convert ORM to Pydantic
#         serialized_data = [schemas.PermissionOut.from_orm(perm) for perm in permissions]

#         return {
#             "status": "success",
#             "result": {
#                 "count": total,
#                 "data": serialized_data
#             }
#         }

#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=str(e)
#         )


# @router.get("/v1/permission/{id}", response_model=schemas.PermissionOut)
# def get_permission(
#     id: int,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Get permission by ID"""
#     permission = db.query(models.Permission).filter(
#         models.Permission.id == id,
#         models.Permission.deleted == False
#     ).first()
    
#     if not permission:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Permission with id {id} not found"
#         )
    
#     return permission


# @router.post("/v1/permission/", 
#             status_code=status.HTTP_201_CREATED, 
#             response_model=schemas.PermissionOut)
# def create_permission(
#     permission: schemas.PermissionCreate,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Create a new permission"""
#     try:
#         # Create permission with user tracking
#         permission_data = permission.dict()
#         new_permission = models.Permission(
#             **permission_data,
#             created_by_user_id=current_user.id,
#             updated_by_user_id=None
#         )
        
#         db.add(new_permission)
#         db.commit()
#         db.refresh(new_permission)

#         return new_permission

#     except HTTPException:
#         raise
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Error creating permission: {str(e)}"
#         )


# @router.patch("/v1/permission/{id}", response_model=schemas.PermissionOut)
# def update_permission(
#     id: int,
#     permission_update: schemas.PermissionUpdate,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Update permission information"""
#     try:
#         permission = db.query(models.Permission).filter(
#             models.Permission.id == id,
#             models.Permission.deleted == False
#         ).first()

#         if not permission:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Permission with id {id} not found"
#             )

#         update_data = permission_update.dict(exclude_unset=True)

#         # Update fields
#         for key, value in update_data.items():
#             setattr(permission, key, value)
        
#         # Track who updated
#         permission.updated_by_user_id = current_user.id

#         db.commit()
#         db.refresh(permission)

#         return permission

#     except HTTPException:
#         raise
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Error updating permission: {str(e)}"
#         )


# @router.delete("/v1/permission/{id}", status_code=status.HTTP_200_OK)
# def delete_permission(
#     id: int,
#     permanent: bool = False,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Soft delete permission (or permanent delete if superuser)"""
#     permission = db.query(models.Permission).filter(
#         models.Permission.id == id
#     ).first()

#     if not permission:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Permission with id {id} not found"
#         )

#     # Check if permission is assigned to any active roles
#     active_roles = db.query(models.Role).join(
#         models.Role.permissions
#     ).filter(
#         models.Permission.id == id,
#         models.Role.deleted == False
#     ).all()
    
#     if active_roles:
#         role_names = ", ".join([role.name for role in active_roles])
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Cannot delete permission. It is assigned to role(s): {role_names}"
#         )

#     # Check if permission is directly assigned to any active users
#     active_users = db.query(models.User).join(
#         models.User.permissions
#     ).filter(
#         models.Permission.id == id,
#         models.User.deleted == False
#     ).all()
    
#     if active_users:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"Cannot delete permission. It is directly assigned to {len(active_users)} user(s)."
#         )

#     if permanent and current_user.is_superuser:
#         # Permanent delete (hard delete) - only for superusers
#         db.delete(permission)
#         db.commit()
#         return {"message": "Permission permanently deleted"}
#     else:
#         # Soft delete with user tracking
#         permission.soft_delete(user_id=current_user.id)
#         db.commit()
#         return {"message": "Permission soft deleted successfully"}


# @router.post("/v1/permission/{id}/restore", response_model=schemas.PermissionOut)
# def restore_permission(
#     id: int,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Restore a soft-deleted permission"""
#     permission = db.query(models.Permission).filter(
#         models.Permission.id == id,
#         models.Permission.deleted == True
#     ).first()

#     if not permission:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Deleted permission with id {id} not found"
#         )

#     permission.restore()
#     permission.updated_by_user_id = current_user.id
#     db.commit()
#     db.refresh(permission)

#     return permission



# app/api/routers/permission.py
from fastapi import APIRouter, Depends, status, Request, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import Optional

from app import database, schemas, models, oauth2
from app.utils import paginate_data, filter_permissions


router = APIRouter(
    prefix="/api/permissions",
    tags=['Permissions']
)


@router.get("/v1/permission/", response_model=schemas.PermissionListResponse)
def get_permissions(
    request: Request,
    skip: int = 0,
    limit: int = 10,
    include_deleted: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user),
):
    """Get all permissions with pagination and filtering"""
    try:
        # Query based on include_deleted flag
        # ✅ OPTIMIZED: Added joinedload for roles if needed
        if include_deleted:
            query = models.Permission.get_all_including_deleted(db).options(
                joinedload(models.Permission.roles)
            )
        else:
            query = models.Permission.get_active(db).options(
                joinedload(models.Permission.roles)
            )
        
        # Apply filters
        query = filter_permissions(request.query_params, query)
        
        total = query.count()
        permissions = query.offset(skip).limit(limit).all()

        # Convert ORM to Pydantic
        serialized_data = [schemas.PermissionOut.from_orm(perm) for perm in permissions]

        return {
            "status": "success",
            "result": {
                "count": total,
                "data": serialized_data
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/v1/permission/{id}", response_model=schemas.PermissionOut)
def get_permission(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Get permission by ID"""
    permission = db.query(models.Permission).filter(
        models.Permission.id == id,
        models.Permission.deleted == False
    ).first()
    
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Permission with id {id} not found"
        )
    
    return permission


# ✅ NEW: Get permission with roles
@router.get("/v1/permission/{id}/with-roles", response_model=schemas.PermissionWithRoles)
def get_permission_with_roles(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Get permission by ID with all roles that have this permission"""
    permission = db.query(models.Permission).options(
        joinedload(models.Permission.roles)
    ).filter(
        models.Permission.id == id,
        models.Permission.deleted == False
    ).first()
    
    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Permission with id {id} not found"
        )
    
    return permission


@router.post("/v1/permission/", 
            status_code=status.HTTP_201_CREATED, 
            response_model=schemas.PermissionOut)
def create_permission(
    permission: schemas.PermissionCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Create a new permission"""
    try:
        # Check if code already exists
        existing = db.query(models.Permission).filter(
            models.Permission.code == permission.code,
            models.Permission.deleted == False
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Permission with code '{permission.code}' already exists"
            )
        
        # Create permission with user tracking
        permission_data = permission.dict()
        new_permission = models.Permission(
            **permission_data,
            created_by_user_id=current_user.id,
            updated_by_user_id=None
        )
        
        db.add(new_permission)
        db.commit()
        db.refresh(new_permission)

        return new_permission

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating permission: {str(e)}"
        )


@router.patch("/v1/permission/{id}", response_model=schemas.PermissionOut)
def update_permission(
    id: int,
    permission_update: schemas.PermissionUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Update permission information"""
    try:
        permission = db.query(models.Permission).filter(
            models.Permission.id == id,
            models.Permission.deleted == False
        ).first()

        if not permission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission with id {id} not found"
            )

        update_data = permission_update.dict(exclude_unset=True)

        # Check if code is being changed and if it conflicts
        if 'code' in update_data and update_data['code'] != permission.code:
            existing = db.query(models.Permission).filter(
                models.Permission.code == update_data['code'],
                models.Permission.deleted == False,
                models.Permission.id != id
            ).first()
            
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Permission with code '{update_data['code']}' already exists"
                )

        # Update fields
        for key, value in update_data.items():
            setattr(permission, key, value)
        
        # Track who updated
        permission.updated_by_user_id = current_user.id

        db.commit()
        db.refresh(permission)

        return permission

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating permission: {str(e)}"
        )


@router.delete("/v1/permission/{id}", status_code=status.HTTP_200_OK)
def delete_permission(
    id: int,
    permanent: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Soft delete permission (or permanent delete if superuser)"""
    # ✅ Load with roles to check relationships
    permission = db.query(models.Permission).options(
        joinedload(models.Permission.roles)
    ).filter(
        models.Permission.id == id
    ).first()

    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Permission with id {id} not found"
        )

    # Check if permission is assigned to any active roles
    active_roles = [role for role in permission.roles if not role.deleted]
    
    if active_roles:
        role_names = ", ".join([role.name for role in active_roles])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete permission. It is assigned to role(s): {role_names}"
        )

    # Check if permission is directly assigned to any active users
    active_users = [user for user in permission.users if not user.deleted]
    
    if active_users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete permission. It is directly assigned to {len(active_users)} user(s)."
        )

    if permanent and current_user.is_superuser:
        # Permanent delete (hard delete) - only for superusers
        # ✅ CASCADE will automatically remove role_permission and user_permission entries
        db.delete(permission)
        db.commit()
        return {"message": "Permission permanently deleted"}
    else:
        # Soft delete with user tracking
        permission.soft_delete(user_id=current_user.id)
        db.commit()
        return {"message": "Permission soft deleted successfully"}


@router.post("/v1/permission/{id}/restore", response_model=schemas.PermissionOut)
def restore_permission(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Restore a soft-deleted permission"""
    permission = db.query(models.Permission).filter(
        models.Permission.id == id,
        models.Permission.deleted == True
    ).first()

    if not permission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deleted permission with id {id} not found"
        )

    permission.restore()
    permission.updated_by_user_id = current_user.id
    db.commit()
    db.refresh(permission)

    return permission