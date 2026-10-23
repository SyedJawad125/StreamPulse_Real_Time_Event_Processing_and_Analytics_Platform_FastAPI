from fastapi import Depends, HTTPException, status
from typing import List, Callable
# from app.dependencies.get_current_user import get_current_user
# ✅ correct import
from app.oauth2 import get_current_user

from app.models import User


def permission_required(required_permissions: List[str]) -> Callable:
    def permission_checker(current_user: User = Depends(get_current_user)):
        if current_user.is_superuser and not hasattr(current_user, "permissions_dict"):
            # Backup logic if someone bypassed
            return

        # Use the dictionary attached to user
        permissions_dict = getattr(current_user, "permissions_dict", {})

        for perm in required_permissions:
            if not permissions_dict.get(perm, False):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing permission: {perm}"
                )
        return
    return permission_checker


def require(*perms: str):
    return Depends(permission_required(list(perms)))



# from fastapi import Depends, HTTPException, status
# from typing import List
# from app.oauth2 import get_current_user
# from app.models import User

# def check_permissions(required_permissions: List[str], user: User):
#     if user.is_superuser:
#         return True
#     return all(user.permissions.get(perm, False) for perm in required_permissions)

# def permission_required(required_permissions: List[str] = None):
#     if required_permissions is None:
#         required_permissions = []
    
#     def dependency(current_user: User = Depends(get_current_user)):
#         if not check_permissions(required_permissions, current_user):
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail=f"Missing required permissions: {', '.join(required_permissions)}"
#             )
#         return current_user
    
#     return dependency

# def require(*permissions: str):
#     return Depends(permission_required(list(permissions)))


# from fastapi import Depends, HTTPException, status
# from app.oauth2 import get_current_user
# from app.models import User

# def permission_required(permission: str):
#     def dependency(current_user: User = Depends(get_current_user)):
#         if not current_user.is_superuser and not current_user.permissions.get(permission, False):
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail=f"Missing permission: {permission}"
#             )
#     return Depends(dependency)