# from fastapi import APIRouter, Depends, status, HTTPException
# from sqlalchemy.orm import Session
# from .. import database, schemas, models, utils, oauth2
# from typing import List
# from app.schemas.user import UserOut
# from ..schemas import LoginRequest, Token
# from .. import database, models, utils, oauth2
# from fastapi.security import OAuth2PasswordRequestForm
# from ..database import get_db
# from fastapi.responses import JSONResponse


# from app import models, schemas, utils, oauth2, database


# router = APIRouter(
#     prefix="/users",
#     tags=['Users']
# )

# # router = APIRouter(tags=['Authentication'])

# # routers/auth.py or similar

# from fastapi import HTTPException
# import traceback



# @router.post("/signup", response_model=schemas.Token)
# async def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
#     try:
#         # Check if user already exists
#         db_user = db.query(models.User).filter(models.User.email == user.email).first()
#         if db_user:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Email already registered"
#             )

#         # Hash password
#         hashed_password = utils.get_password_hash(user.password)

#         # Superuser flag (optional)
#         is_superuser = getattr(user, "is_superuser", False)

#         # Validate role only if not superuser
#         role = None
#         if not is_superuser:
#             if user.role_id is None:
#                 raise HTTPException(
#                     status_code=status.HTTP_400_BAD_REQUEST,
#                     detail="role_id is required for non-superusers"
#                 )

#             role = db.query(models.Role).filter(models.Role.id == user.role_id).first()
#             if not role:
#                 raise HTTPException(
#                     status_code=status.HTTP_404_NOT_FOUND,
#                     detail="Role not found"
#                 )

#         # Create user
#         new_user = models.User(
#             username=user.username,
#             email=user.email,
#             hashed_password=hashed_password,
#             is_active=True,
#             is_superuser=is_superuser,
#             role_id=user.role_id if not is_superuser else None
#         )

#         db.add(new_user)
#         db.commit()
#         db.refresh(new_user)

#         # Create token
#         access_token = oauth2.create_access_token(data={"user_id": new_user.id})
#         return {"access_token": access_token, "token_type": "bearer"}

#     except HTTPException:
#         raise  # Re-raise HTTPExceptions without modification
#     except Exception as e:
#         traceback.print_exc()
#         raise HTTPException(status_code=500, detail="Internal server error")


# # @router.post("/login", response_model=Token)

# # router = APIRouter(tags=["Authentication"])


# @router.post("/login")
# def login(user_credentials: schemas.LoginRequest, db: Session = Depends(database.get_db)):
#     # Step 1: Authenticate user
#     user = db.query(models.User).filter(models.User.email == user_credentials.email).first()

#     if not user or not utils.verify_password(user_credentials.password, user.hashed_password):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Incorrect email or password"
#         )

#     # Step 2: Check if user is active (optional)
#     if hasattr(user, "is_active") and not user.is_active:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Account is disabled"
#         )

#     # Step 3: Load all permissions and initialize permissions_dict
#     all_permissions = db.query(models.Permission).all()
#     permissions_dict = {perm.code: False for perm in all_permissions}

#     # Step 4: Determine is_superuser based on role
#     is_superuser_response = False

#     if user.is_superuser and not user.role:
#         for perm in all_permissions:
#             permissions_dict[perm.code] = True
#         is_superuser_response = True

#     elif user.role:
#         for perm in user.role.permissions:
#             permissions_dict[perm.code] = True

#     else:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="User has no role assigned"
#         )

#     # Step 5: Create access and refresh tokens
#     access_token = oauth2.create_access_token(data={"user_id": user.id})
#     refresh_token = oauth2.create_refresh_token(data={"user_id": user.id})

#     # Step 6: Prepare response
#     response_data = {
#         "message": "Successful",
#         "access_token": access_token,
#         "refresh_token": refresh_token,
#         "token_type": "bearer",
#         "user_id": user.id,
#         "username": user.username,
#         "email": user.email,
#         "is_superuser": is_superuser_response,
#         "role_id": user.role.id if user.role else None,
#         "role_name": user.role.name if user.role else None,
#         "permissions": permissions_dict
#     }

#     # Step 7: Return response with status code
#     return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)
    
    
# # For personal profile
# @router.get("/me", response_model=schemas.UserOut)
# def get_me(current_user: models.User = Depends(oauth2.get_current_user)):
#     return current_user

# # For admin or other users
# @router.get("/{id}", response_model=schemas.UserOut)
# def get_user(id: int, db: Session = Depends(database.get_db),
#              current_user: models.User = Depends(oauth2.get_current_user)):
#     if current_user.id != id and not current_user.is_admin:
#         raise HTTPException(status_code=403, detail="Not authorized to access this user's information")
    
#     user = db.query(models.User).filter(models.User.id == id).first()
#     if not user:
#         raise HTTPException(status_code=404, detail=f"User with id {id} not found")
    
#     return user


# @router.get("/", response_model=List[schemas.UserOut])
# def get_all_users(db: Session = Depends(database.get_db), 
#                  current_user: models.User = Depends(oauth2.get_current_user)):
#     # Only allow admin to view all users
#     if not current_user.is_admin:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Only admin users can view all users"
#         )
    
#     users = db.query(models.User).all()
#     return users

# @router.put("/{id}", response_model=schemas.UserOut)
# def update_user(id: int, updated_user: schemas.UserCreate, 
#                db: Session = Depends(database.get_db), 
#                current_user: models.User = Depends(oauth2.get_current_user)):
#     # Only allow users to update their own profile or admin to update any profile
#     if current_user.id != id and not current_user.is_admin:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Not authorized to update this user's information"
#         )
    
#     user_query = db.query(models.User).filter(models.User.id == id)
#     user = user_query.first()
    
#     if not user:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"User with id {id} not found"
#         )
    
#     # Hash the password if it's being updated
#     if updated_user.password:
#         updated_user.password = utils.get_password_hash(updated_user.password)
    
#     user_query.update(updated_user.dict(), synchronize_session=False)
#     db.commit()
#     return user_query.first()

# @router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
# def delete_user(id: int, db: Session = Depends(database.get_db), 
#                current_user: models.User = Depends(oauth2.get_current_user)):
#     # Only allow admin to delete users or users to delete themselves
#     # if current_user.id != id and not current_user.is_admin:
#     #     raise HTTPException(
#     #         status_code=status.HTTP_403_FORBIDDEN,
#     #         detail="Not authorized to delete this user"
#     #     )
    
#     user_query = db.query(models.User).filter(models.User.id == id)
#     user = user_query.first()
    
#     if not user:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"User with id {id} not found"
#         )
    
#     user_query.delete(synchronize_session=False)
#     db.commit()
#     return




# # @router.post("/signup", response_model=schemas.Token)
# # async def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
# #     try:
# #         # Check if user already exists
# #         db_user = db.query(models.User).filter(models.User.email == user.email).first()
# #         if db_user:
# #             raise HTTPException(
# #                 status_code=status.HTTP_400_BAD_REQUEST,
# #                 detail="Email already registered"
# #             )

# #         # Check if role exists
# #         role = db.query(models.Role).filter(models.Role.id == user.role_id).first()
# #         if not role:
# #             raise HTTPException(
# #                 status_code=status.HTTP_404_NOT_FOUND,
# #                 detail="Role not found"
# #             )

# #         # Hash password
# #         hashed_password = utils.get_password_hash(user.password)

# #         # Create user
# #         new_user = models.User(
# #             username=user.username,
# #             email=user.email,
# #             hashed_password=hashed_password,
# #             is_active=True,
# #             role_id=user.role_id
# #         )

# #         db.add(new_user)
# #         db.commit()
# #         db.refresh(new_user)

# #         # Token
# #         access_token = oauth2.create_access_token(data={"user_id": new_user.id})
# #         return {"access_token": access_token, "token_type": "bearer"}

# #     except Exception as e:
# #         traceback.print_exc()  # Show error in terminal
# #         raise HTTPException(status_code=500, detail=str(e))




# # @router.post("/login")
# # def login(user_credentials: schemas.LoginRequest, db: Session = Depends(database.get_db)):
# #     # Step 1: Authenticate user
# #     user = db.query(models.User).filter(models.User.email == user_credentials.email).first()
    
# #     if not user or not utils.verify_password(user_credentials.password, user.hashed_password):
# #         raise HTTPException(
# #             status_code=status.HTTP_403_FORBIDDEN,
# #             detail="Incorrect email or password"
# #         )

# #     # Step 2: (Optional) Check if user is active
# #     if hasattr(user, "is_active") and not user.is_active:
# #         raise HTTPException(
# #             status_code=status.HTTP_403_FORBIDDEN,
# #             detail="Account is disabled"
# #         )

# #     # Step 3: Load all permissions to prepare a permission map
# #     all_permissions = db.query(models.Permission).all()
# #     permissions_dict = {perm.code: False for perm in all_permissions}

# #     # Step 4: Assign permissions
# #     if user.is_superuser and not user.role:
# #         # Superuser with no role gets full access
# #         for perm in all_permissions:
# #             permissions_dict[perm.code] = True
# #     elif user.role:
# #         # Regular user or superuser with a role gets role-specific permissions
# #         for perm in user.role.permissions:
# #             permissions_dict[perm.code] = True
# #     else:
# #         # No role assigned
# #         raise HTTPException(
# #             status_code=status.HTTP_400_BAD_REQUEST,
# #             detail="User has no role assigned"
# #         )

# #     # Step 5: Create access token
# #     access_token = oauth2.create_access_token(data={"user_id": user.id})

# #     # Step 6: Return full response
# #     return {
# #         "message": "Successful",
# #         "access_token": access_token,
# #         "token_type": "bearer",
# #         "user_id": user.id,
# #         "username": user.username,
# #         "email": user.email,
# #         "is_superuser": bool(user.is_superuser),  # ✅ Always return true or false correctly
# #         "role_id": user.role.id if user.role else None,
# #         "role_name": user.role.name if user.role else None,
# #         "permissions": permissions_dict
# #     }








# app/api/routers/user.py
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from fastapi.responses import JSONResponse

from app import models, schemas, utils, oauth2, database
from app.database import get_db


router = APIRouter(
    prefix="/api/user",
    tags=['Users']
)


@router.post("/v1/signup/", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    user: schemas.UserCreate, 
    db: Session = Depends(get_db)
):
    """Register a new user"""
    try:
        # Check if user already exists (including soft-deleted)
        existing_user = db.query(models.User).filter(
            models.User.email == user.email
        ).first()
        
        if existing_user and not existing_user.deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        if existing_user and existing_user.deleted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This email was previously registered. Please contact support."
            )

        # Validate role for non-superusers
        if not user.is_superuser:
            if user.role_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="role_id is required for non-superusers"
                )
            
            role = db.query(models.Role).filter(
                models.Role.id == user.role_id,
                models.Role.deleted == False
            ).first()
            
            if not role:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Role not found"
                )

        # Hash password
        hashed_password = utils.get_password_hash(user.password)

        # Create user
        new_user = models.User(
            username=user.username,
            email=user.email,
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=user.is_superuser,
            role_id=user.role_id if not user.is_superuser else None
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return new_user

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating user: {str(e)}"
        )


@router.post("/v1/login/")
def login(
    user_credentials: schemas.LoginRequest, 
    db: Session = Depends(get_db)
):
    """User login endpoint"""
    # Authenticate user (only active, non-deleted users)
    user = db.query(models.User).filter(
        models.User.email == user_credentials.email,
        models.User.deleted == False
    ).first()

    if not user or not utils.verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect email or password"
        )

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    # Load all permissions
    all_permissions = db.query(models.Permission).filter(
        models.Permission.deleted == False
    ).all()
    
    permissions_dict = {perm.code: False for perm in all_permissions}

    # Determine permissions
    is_superuser_response = False

    if user.is_superuser:
        # Superuser gets all permissions
        for perm in all_permissions:
            permissions_dict[perm.code] = True
        is_superuser_response = True
    elif user.role:
        # Regular user gets role permissions
        for perm in user.role.permissions:
            if not perm.deleted:
                permissions_dict[perm.code] = True
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no role assigned"
        )

    # Create tokens
    access_token = oauth2.create_access_token(data={"user_id": user.id})
    refresh_token = oauth2.create_refresh_token(data={"user_id": user.id})

    # Prepare response
    response_data = {
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_superuser": is_superuser_response,
            "role_id": user.role.id if user.role else None,
            "role_name": user.role.name if user.role else None,
        },
        "permissions": permissions_dict
    }

    return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)


@router.get("/v1/me/", response_model=schemas.UserOut)
def get_current_user_profile(
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Get current logged-in user profile"""
    return current_user


@router.get("/v1/all/users/", response_model=schemas.UserListResponse)
def get_all_users(
    skip: int = 0,
    limit: int = 10,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Get all users (superuser only) with pagination"""
    # Only superuser can view all users
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superusers can view all users"
        )
    
    # Query based on include_deleted flag
    if include_deleted:
        query = models.User.get_all_including_deleted(db)
    else:
        query = models.User.get_active(db)
    
    total = query.count()
    users = query.offset(skip).limit(limit).all()
    
    return {
        "status": "success",
        "result": {
            "count": total,
            "data": users
        }
    }


@router.get("/{id}", response_model=schemas.UserOut)
def get_user(
    id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Get user by ID"""
    # Users can view their own profile, superusers can view any profile
    if current_user.id != id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this user's information"
        )
    
    user = db.query(models.User).filter(
        models.User.id == id,
        models.User.deleted == False
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} not found"
        )
    
    return user


@router.patch("/{id}", response_model=schemas.UserOut)
def update_user(
    id: int,
    user_update: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Update user information"""
    # Users can update their own profile, superusers can update any profile
    if current_user.id != id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user's information"
        )
    
    user = db.query(models.User).filter(
        models.User.id == id,
        models.User.deleted == False
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} not found"
        )
    
    # Get update data (only fields that were provided)
    update_data = user_update.dict(exclude_unset=True)
    
    # Hash password if being updated
    if "password" in update_data:
        update_data["hashed_password"] = utils.get_password_hash(update_data["password"])
        del update_data["password"]
    
    # Update fields
    for field, value in update_data.items():
        setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    
    return user


@router.delete("/{id}", status_code=status.HTTP_200_OK)
def delete_user(
    id: int,
    permanent: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Soft delete user (or permanent delete if superuser)"""
    # Only superuser can delete users
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superusers can delete users"
        )
    
    user = db.query(models.User).filter(models.User.id == id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} not found"
        )
    
    # Prevent self-deletion
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    if permanent and current_user.is_superuser:
        # Permanent delete (hard delete)
        db.delete(user)
        db.commit()
        return {"message": "User permanently deleted"}
    else:
        # Soft delete
        user.soft_delete()
        db.commit()
        return {"message": "User soft deleted successfully"}


@router.post("/{id}/restore", response_model=schemas.UserOut)
def restore_user(
    id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Restore a soft-deleted user (superuser only)"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superusers can restore users"
        )
    
    user = db.query(models.User).filter(
        models.User.id == id,
        models.User.deleted == True
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deleted user with id {id} not found"
        )
    
    user.restore()
    db.commit()
    db.refresh(user)
    
    return user