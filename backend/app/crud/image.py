from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException
from app.models.image import Image
from app.schemas import ImageCreate, ImageUpdate
import shutil
import os
from datetime import datetime
from pathlib import Path
import uuid
import imghdr
from typing import Set, Optional

UPLOAD_DIR = "uploaded_images"
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_IMAGE_TYPES: Set[str] = {"jpeg", "jpg", "png", "gif"}

def validate_image(file: UploadFile) -> None:
    # Check file size
    file.file.seek(0, 2)  # Seek to end
    size = file.file.tell()
    file.file.seek(0)  # Reset position
    
    if size > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size {size} exceeds maximum allowed size of {MAX_IMAGE_SIZE}"
        )
    
    # Check file type
    contents = file.file.read(1024)  # Read first 1KB for type checking
    file.file.seek(0)  # Reset position
    
    image_type = imghdr.what(None, contents)
    if not image_type or image_type.lower() not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type {image_type} not allowed. Must be one of: {ALLOWED_IMAGE_TYPES}"
        )

def generate_unique_filename(original_filename: Optional[str]) -> str:
    # Get file extension from original filename
    ext = Path(original_filename or "image.jpg").suffix
    # Generate unique filename
    return f"{uuid.uuid4()}{ext}"

from pathlib import Path
import os
from datetime import datetime

def save_image_file(file: UploadFile):
    """Helper function to save uploaded file to disk"""
    try:
        # Create upload directory if it doesn't exist
        upload_dir = Path("uploads/images")
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_ext = file.filename.split(".")[-1] if "." in file.filename else ""
        filename = f"{timestamp}.{file_ext}" if file_ext else timestamp
        file_path = upload_dir / filename
        
        # Save the file
        with open(file_path, "wb") as buffer:
            buffer.write(file.file.read())
        
        return {
            "image_path": str(file_path),
            "original_filename": file.filename,
            "file_size": os.path.getsize(file_path),
            "mime_type": file.content_type
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to save image file: {str(e)}"
        )

def get_image_url(image_path: str) -> str:
    """Convert file system path to URL path"""
    return f"/images/files/{os.path.basename(image_path)}"

def create_image(db: Session, file: UploadFile, image_data: ImageCreate) -> Image:
    try:
        # 1. Save the file first
        file_info = save_image_file(file)
        
        # 2. Prepare complete image data
        image_dict = image_data.dict(exclude={"image_path"})  # Remove if present in schema
        image_dict.update({
            "image_path": file_info["image_path"],
            "upload_date": datetime.utcnow(),
            "original_filename": file_info.get("original_filename"),
            "file_size": file_info.get("file_size"),
            "mime_type": file_info.get("mime_type")
        })
        
        # 3. Create and save the image record
        db_image = Image(**image_dict)
        db.add(db_image)
        db.commit()
        db.refresh(db_image)
        
        return db_image
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        db.rollback()
        # Clean up the saved file if database operation failed
        if 'file_info' in locals() and file_info.get("image_path"):
            try:
                Path(file_info["image_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to create image record: {str(e)}"
        )

def get_image(db: Session, image_id: int) -> Image:
    return db.query(Image).filter(Image.id == image_id).first()

def get_all_images(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Image).offset(skip).limit(limit).all()

def update_image(db: Session, db_image: Image, update_data: ImageUpdate) -> Image:
    try:
        update_dict = update_data.dict(exclude_unset=True)
        
        for field, value in update_dict.items():
            setattr(db_image, field, value)
        
        db.commit()
        db.refresh(db_image)
        return db_image
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to update image: {str(e)}"
        )


def delete_image(db: Session, image_id: int) -> bool:
    db_image = db.query(Image).filter(Image.id == image_id).first()
    if db_image:
        # Delete the physical file first
        try:
            # Get the image path value from the ORM object
            db_image_path = db.query(Image.image_path).filter(Image.id == image_id).scalar()
            image_path = str(db_image_path) if db_image_path else None
            
            if image_path and os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            # Log the error but continue with database deletion
            print(f"Error deleting file {image_path}: {str(e)}")
        
        # Delete database record
        db.delete(db_image)
        db.commit()
        return True
    return False
