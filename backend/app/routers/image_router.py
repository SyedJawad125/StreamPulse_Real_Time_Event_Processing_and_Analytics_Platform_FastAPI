# app/routers/image_router.py

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
import os, shutil

from app.database import get_db
from app.models.image import Image

router = APIRouter()
UPLOAD_DIR = "static/hotel_images"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/-image/upload")
async def upload_image(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(None),
    bulletsdescription: str = Form(None),
    category_id: int = Form(None),
    created_by_user_id: int = Form(None),
    db: Session = Depends(get_db),
):
    try:
        save_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        new_image = Image(
            image_path=save_path,
            original_filename=file.filename,
            file_size=os.path.getsize(save_path),
            mime_type=file.content_type,
            name=name,
            description=description,
            bulletsdescription=bulletsdescription,
            category_id=category_id,
            created_by_user_id=created_by_user_id,
        )

        db.add(new_image)
        db.commit()
        db.refresh(new_image)

        return {"success": True, "image_id": new_image.id}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
