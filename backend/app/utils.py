from fastapi import HTTPException
from passlib.context import CryptContext
from datetime import datetime
from app import models
from sqlalchemy.orm import Query
from app import models, schemas 
from fastapi.responses import JSONResponse

 # ✅ Keep this if enums are in the same schemas file


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)


def paginate_data(data, request):
    try:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        start = (page - 1) * page_size
        end = start + page_size
        return data[start:end], len(data)
    except:
        return data, len(data)
    
from fastapi.responses import JSONResponse
def create_response(data, message, status_code):
    return JSONResponse(
        status_code=status_code,
        content={
            "status": message,
            "result": data
        }
    )




def filter_employees(params, query):
    name = params.get("name")
    if name:
        query = query.filter(models.Employee.name.ilike(f"%{name}%"))
    # Add more filters as needed
    return query

def filter_ranks(params, query):
    title = params.get("title")
    if title:
        query = query.filter(models.Rank.title.ilike(f"%{title}%"))
    # Add more filters as needed
    return query

def filter_attendances(params, query):
    is_present = params.get("is_present")
    date = params.get("date")
    employee_id = params.get("employee_id")

    # Handle is_present filter
    if is_present is not None:
        is_present = is_present.lower()
        if is_present in ["true", "1"]:
            query = query.filter(models.Attendance.is_present == True)
        elif is_present in ["false", "0"]:
            query = query.filter(models.Attendance.is_present == False)

    # Handle date filter
    if date:
        try:
            # Optional: Validate the date format
            from datetime import datetime
            datetime.strptime(date, "%Y-%m-%d")  # Will raise ValueError if invalid
            query = query.filter(models.Attendance.date == date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # Handle employee_id filter
    if employee_id:
        try:
            query = query.filter(models.Attendance.employee_id == int(employee_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid employee_id. Must be an integer.")

    return query
    

from starlette.datastructures import QueryParams
from app.models.image import ImageCategory


def filter_image_categories(query_params: QueryParams, query: Query) -> Query:
    category = query_params.get("category")
    created_by_user_id = query_params.get("created_by_user_id")
    updated_by_user_id = query_params.get("updated_by_user_id")

    if category:
        query = query.filter(ImageCategory.category.ilike(f"%{category}%"))

    if created_by_user_id:
        try:
            query = query.filter(ImageCategory.created_by_user_id == int(created_by_user_id))
        except ValueError:
            pass

    if updated_by_user_id:
        try:
            query = query.filter(ImageCategory.updated_by_user_id == int(updated_by_user_id))
        except ValueError:
            pass

    return query

from sqlalchemy.orm import Session
from app.models.image import Image
from typing import List, Optional


def filter_images(
    db: Session,
    name: Optional[str] = None,
    category_id: Optional[int] = None,
    created_by_user_id: Optional[int] = None,
    mime_type: Optional[str] = None
) -> List[Image]:
    query = db.query(Image)

    if name:
        query = query.filter(Image.name.ilike(f"%{name}%"))
    if category_id:
        query = query.filter(Image.category_id == category_id)
    if created_by_user_id:
        query = query.filter(Image.created_by_user_id == created_by_user_id)
    if mime_type:
        query = query.filter(Image.mime_type == mime_type)

    return query.all()

from typing import Any
from fastapi import Request
from sqlalchemy.orm import Query
from app.models.image import Image  # make sure this import is correct

def filter_images_all(query_params: dict[str, Any], query: Query) -> Query:
    """
    Dynamically filter images based on query parameters.
    Supported filters: name, category_id, created_by_user_id, mime_type
    """
    name = query_params.get("name")
    category_id = query_params.get("category_id")
    created_by_user_id = query_params.get("created_by_user_id")
    mime_type = query_params.get("mime_type")

    if name:
        query = query.filter(Image.name.ilike(f"%{name}%"))
    if category_id:
        try:
            query = query.filter(Image.category_id == int(category_id))
        except ValueError:
            pass  # Skip invalid category_id
    if created_by_user_id:
        try:
            query = query.filter(Image.created_by_user_id == int(created_by_user_id))
        except ValueError:
            pass
    if mime_type:
        query = query.filter(Image.mime_type == mime_type)

    return query

def filter_permissions(params, query):
    name = params.get("name")
    if name:
        query = query.filter(models.Permission.name.ilike(f"%{name}%"))
    # Add more filters as needed
    return query


def filter_roles(params, query):
    name = params.get("name")
    if name:
        query = query.filter(models.Role.name.ilike(f"%{name}%"))
    # Add more filters as needed
    return query




import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

def send_email_notification(to_email: str, subject: str, message: str):
    sender_email = os.getenv("EMAIL_USER", "default@gmail.com")
    sender_password = os.getenv("EMAIL_PASSWORD", "")
    email_host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    email_port = int(os.getenv("EMAIL_PORT", 465))

    print(f"Preparing to send email to: {to_email}")
    print(f"SMTP Server: {email_host}:{email_port}, From: {sender_email}")

    msg = MIMEText(message)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL(email_host, email_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        print(f"[SUCCESS] Email sent to {to_email}")
    except Exception as e:
        print("[ERROR] Failed to send email:", str(e))

import os
from datetime import datetime

LOG_FILE_PATH = "app/logs/leave_actions.log"  # You can customize the path

def log_action(message: str):
    print("📄 Writing log:", message)  # TEMP
    os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
    with open(LOG_FILE_PATH, "a") as log_file:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        log_file.write(f"[{timestamp}] {message}\n")


# EMAIL_HOST = "smtp.gmail.com"
# EMAIL_USE_SSL = True
# EMAIL_PORT = 465
# EMAIL_HOST_USER = "syedjawadali92@gmail.com"
# EMAIL_HOST_PASSWORD = "ctpgxfclwyucweni"


# app/utils/redis_client.py

import redis
from redis.exceptions import RedisError
import os

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

try:
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    redis_client.ping()  # Try connecting to Redis
    print("✅ Redis connected successfully.")
except RedisError as e:
    print("❌ Redis connection failed:", e)
    redis_client = None

from fastapi import HTTPException
from sqlalchemy.orm import Query

def get_object_or_404(query: Query, id: int, name: str = "Object"):
    obj = query.filter_by(id=id).first()
    if not obj:
        raise HTTPException(status_code=404, detail=f"{name} with id {id} not found")
    return obj
