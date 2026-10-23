from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from . import models, database
from .config import settings

# Define OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# JWT configuration
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 7  # Refresh tokens valid for 7 days

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_refresh_token(refresh_token: str) -> dict:
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token type"
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(database.get_db)):
    print("🔐 get_current_user called")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Verify token type
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
            
        user_id = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
        user_id = int(user_id)  # Convert to int explicitly
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception

    # Load all permissions
    all_permissions = db.query(models.Permission).all()
    permissions_dict = {perm.code: False for perm in all_permissions}

    # Determine permissions based on role or superuser
    is_superuser = bool(user.is_superuser)  # Convert SQLAlchemy boolean to Python boolean
    if is_superuser and not user.role:
        # Superuser with no role: full access
        for perm in all_permissions:
            permissions_dict[perm.code] = True
    elif user.role:
        for perm in user.role.permissions:
            permissions_dict[perm.code] = True
    else:
        # No role, not superuser = invalid setup
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no role assigned"
        )

    # Attach to user for permission checks
    user.permissions_dict = permissions_dict

    return user
