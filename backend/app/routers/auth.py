# from fastapi import APIRouter, Depends, status, HTTPException
# from fastapi.security.oauth2 import OAuth2PasswordRequestForm
# from sqlalchemy.orm import Session
# from .. import database, schemas, models, utils, oauth2

# router = APIRouter(tags=['Authentication'])

# @router.post('/login', response_model=schemas.TokenResponse)
# def login(user_credentials: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
#     user = db.query(models.User).filter(
#         models.User.email == user_credentials.username).first()

#     if not user:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Credentials")

#     if not utils.verify_password(user_credentials.password, user.password):
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Credentials")

#     # Create both access and refresh tokens
#     access_token = oauth2.create_access_token(data={"user_id": user.id})
#     refresh_token = oauth2.create_refresh_token(data={"user_id": user.id})

#     return {
#         "access_token": access_token,
#         "refresh_token": refresh_token,
#         "token_type": "bearer"
#     }

# @router.post('/refresh', response_model=schemas.TokenResponse)
# def refresh_token(refresh_token: str, db: Session = Depends(database.get_db)):
#     # Verify the refresh token
#     payload = oauth2.verify_refresh_token(refresh_token)
    
#     # Get user from payload
#     user_id = payload.get("user_id")
#     if not user_id:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid refresh token"
#         )
    
#     # Verify user still exists
#     user = db.query(models.User).filter(models.User.id == user_id).first()
#     if not user:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="User no longer exists"
#         )
    
#     # Create new tokens
#     access_token = oauth2.create_access_token(data={"user_id": user.id})
#     new_refresh_token = oauth2.create_refresh_token(data={"user_id": user.id})
    
#     return {
#         "access_token": access_token,
#         "refresh_token": new_refresh_token,
#         "token_type": "bearer"
#     }

# @router.post('/logout')
# def logout(current_user: models.User = Depends(oauth2.get_current_user)):
#     # In a real implementation, you would add the token to a blacklist
#     # This could be done using Redis or a database table
#     return {"message": "Successfully logged out"}








# app/api/routers/auth.py
from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.security.oauth2 import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse
from typing import Optional

from app import database, schemas, models, utils, oauth2
from app.database import get_db


router = APIRouter(
    prefix="/api/auth",
    tags=['Authentication']
)


@router.post('/v1/login/')
def login(
    user_credentials: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    User login with OAuth2 form (username field contains email)
    Returns access token, refresh token, user info, and permissions
    """
    # Query user (only active, non-deleted users)
    user = db.query(models.User).filter(
        models.User.email == user_credentials.username,  # OAuth2 uses 'username' field
        models.User.deleted == False
    ).first()

    # Check if user exists
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid credentials"
        )

    # Verify password (use hashed_password, not password)
    if not utils.verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid credentials"
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
    elif user.role and not user.role.deleted:
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
            "is_active": user.is_active,
            "is_superuser": is_superuser_response,
            "role_id": user.role.id if user.role else None,
            "role_name": user.role.name if user.role else None,
        },
        "permissions": permissions_dict
    }

    return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)


@router.post('/login-json')
def login_json(
    user_credentials: schemas.LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Alternative login endpoint using JSON body instead of form data
    Same response as /login
    """
    # Query user (only active, non-deleted users)
    user = db.query(models.User).filter(
        models.User.email == user_credentials.email,
        models.User.deleted == False
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid credentials"
        )

    # Verify password
    if not utils.verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid credentials"
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
        for perm in all_permissions:
            permissions_dict[perm.code] = True
        is_superuser_response = True
    elif user.role and not user.role.deleted:
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
            "is_active": user.is_active,
            "is_superuser": is_superuser_response,
            "role_id": user.role.id if user.role else None,
            "role_name": user.role.name if user.role else None,
        },
        "permissions": permissions_dict
    }

    return JSONResponse(status_code=status.HTTP_200_OK, content=response_data)


@router.post('/refresh', response_model=schemas.TokenResponse)
def refresh_token(
    refresh_token: str,
    db: Session = Depends(get_db)
):
    """
    Refresh access token using refresh token
    """
    try:
        # Verify the refresh token
        payload = oauth2.verify_refresh_token(refresh_token)
        
        # Get user from payload
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Verify user still exists and is active (not deleted)
        user = db.query(models.User).filter(
            models.User.id == user_id,
            models.User.deleted == False
        ).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User no longer exists or is deleted",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Check if user is still active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled"
            )
        
        # Create new tokens
        new_access_token = oauth2.create_access_token(data={"user_id": user.id})
        new_refresh_token = oauth2.create_refresh_token(data={"user_id": user.id})
        
        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"}
        )


@router.post('/logout')
def logout(
    current_user: models.User = Depends(oauth2.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Logout endpoint - In production, implement token blacklisting
    
    For now, this is a placeholder. To implement properly:
    1. Use Redis to store blacklisted tokens
    2. Check token against blacklist in oauth2.get_current_user
    3. Set token TTL equal to JWT expiry
    
    Example Redis implementation:
    - Store: redis.setex(f"blacklist:{token}", settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, "1")
    - Check: redis.exists(f"blacklist:{token}")
    """
    return {
        "message": "Successfully logged out. Please delete the token from client side.",
        "note": "This is a client-side logout. Server-side token blacklisting requires Redis."
    }


@router.post('/verify-token')
def verify_token(
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """
    Verify if the current access token is valid
    Returns current user info
    """
    return {
        "message": "Token is valid",
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "is_active": current_user.is_active,
            "is_superuser": current_user.is_superuser,
            "role_id": current_user.role_id
        }
    }


@router.post('/change-password')
def change_password(
    old_password: str,
    new_password: str,
    current_user: models.User = Depends(oauth2.get_current_user),
    db: Session = Depends(get_db)
):
    """
    Change password for currently logged-in user
    """
    # Verify old password
    if not utils.verify_password(old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect old password"
        )
    
    # Validate new password
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long"
        )
    
    if old_password == new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from old password"
        )
    
    # Update password
    current_user.hashed_password = utils.get_password_hash(new_password)
    db.commit()
    
    return {
        "message": "Password changed successfully"
    }


@router.post('/request-password-reset')
def request_password_reset(
    email: str,
    db: Session = Depends(get_db)
):
    """
    Request password reset - sends reset link to email
    (Placeholder - implement email sending logic)
    """
    # Find user by email
    user = db.query(models.User).filter(
        models.User.email == email,
        models.User.deleted == False
    ).first()
    
    # Always return success to prevent email enumeration
    # In production, send email with reset token
    if user and user.is_active:
        # Generate password reset token
        reset_token = oauth2.create_access_token(
            data={"user_id": user.id, "type": "password_reset"},
            expires_delta_minutes=30  # 30 minutes expiry
        )
        
        # TODO: Send email with reset link containing the token
        # send_password_reset_email(user.email, reset_token)
        
        print(f"Password reset token for {user.email}: {reset_token}")
    
    return {
        "message": "If an account with that email exists, a password reset link has been sent."
    }


@router.post('/reset-password')
def reset_password(
    token: str,
    new_password: str,
    db: Session = Depends(get_db)
):
    """
    Reset password using reset token from email
    """
    try:
        # Verify token
        payload = oauth2.verify_access_token(token, credentials_exception=HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset token"
        ))
        
        # Check token type
        if payload.get("type") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid reset token"
            )
        
        # Get user
        user = db.query(models.User).filter(
            models.User.id == user_id,
            models.User.deleted == False
        ).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Validate new password
        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long"
            )
        
        # Update password
        user.hashed_password = utils.get_password_hash(new_password)
        db.commit()
        
        return {
            "message": "Password reset successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset token"
        )