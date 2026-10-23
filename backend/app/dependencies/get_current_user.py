# from fastapi import Depends, HTTPException, status
# from fastapi.security import OAuth2PasswordBearer
# from jose import jwt, JWTError
# from sqlalchemy.orm import Session, joinedload
# from app.database import get_db
# from app.models import User

# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")  # adjust path if needed

# SECRET_KEY = "your-secret-key"  # ✅ must match token creation
# ALGORITHM = "HS256"

# def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
#     print("Token received:", token)  # 👈 log this
#     try:
#         payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
#         print("Decoded payload:", payload)  # 🐞 debug
#         user_id = payload.get("user_id")
#         if user_id is None:
#             raise HTTPException(status_code=401, detail="Invalid token payload")
#     except JWTError:
#         raise HTTPException(status_code=401, detail="Invalid token")

#     user = db.query(User).options(joinedload(User.permissions)).filter(User.id == user_id).first()

#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")

#     return user
