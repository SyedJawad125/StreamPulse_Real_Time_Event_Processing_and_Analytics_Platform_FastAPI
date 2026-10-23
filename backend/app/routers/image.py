# # app/api/routers/image.py
# from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request, Query
# from sqlalchemy.orm import Session, joinedload
# from typing import Optional
# from pathlib import Path
# import os
# import shutil
# from datetime import datetime
# import uuid

# from app import database, models, oauth2, schemas
# from app.utils import paginate_data, filter_images
# from app.dependencies.permission import require
# from rest_framework import status


# router = APIRouter(
#     prefix="/api/images",
#     tags=['Images']
# )

# # Configuration
# UPLOAD_DIR = "static/images"
# os.makedirs(UPLOAD_DIR, exist_ok=True)


# def save_image_file(file: UploadFile) -> dict:
#     """Save uploaded image file and return file information"""
#     try:
#         # Generate unique filename
#         file_extension = Path(file.filename).suffix
#         unique_filename = f"{uuid.uuid4()}{file_extension}"
#         save_path = os.path.join(UPLOAD_DIR, unique_filename)
        
#         # Save file
#         with open(save_path, "wb") as buffer:
#             shutil.copyfileobj(file.file, buffer)
        
#         return {
#             "image_path": save_path,
#             "original_filename": file.filename,
#             "file_size": os.path.getsize(save_path),
#             "mime_type": file.content_type
#         }
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Error saving file: {str(e)}"
#         )


# @router.get("/v1/image/", response_model=schemas.ImageListResponse, dependencies=[require("read_image")])
# def get_images(
#     request: Request,
#     skip: int = 0,
#     limit: int = 10,
#     include_deleted: bool = False,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user),
# ):
#     """Get all images with pagination and filtering"""
#     try:
#         # Query based on include_deleted flag
#         if include_deleted:
#             query = models.Image.get_all_including_deleted(db)
#         else:
#             query = models.Image.get_active(db)
        
#         # Apply filters directly without the problematic filter_images function
#         query_params_dict = dict(request.query_params)
        
#         # Apply common filters
#         if 'category_id' in query_params_dict:
#             category_id = query_params_dict['category_id']
#             if isinstance(category_id, list):
#                 category_id = category_id[0]
#             query = query.filter(models.Image.category_id == int(category_id))
        
#         if 'name' in query_params_dict:
#             name = query_params_dict['name']
#             if isinstance(name, list):
#                 name = name[0]
#             query = query.filter(models.Image.name.ilike(f"%{name}%"))
        
#         if 'is_active' in query_params_dict:
#             is_active = query_params_dict['is_active']
#             if isinstance(is_active, list):
#                 is_active = is_active[0]
#             is_active_bool = is_active.lower() in ['true', '1', 'yes']
#             query = query.filter(models.Image.is_active == is_active_bool)
        
#         # Add more filters as needed...
        
#         total = query.count()
#         images = query.offset(skip).limit(limit).all()

#         # Convert ORM to Pydantic
#         serialized_data = [schemas.ImageWithCategory.from_orm(img) for img in images]

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

# from fastapi import Query, Path

# @router.get("/v1/image/by/category/{category}", response_model=schemas.ImageListResponse, dependencies=[require("read_image")])
# def get_images_by_category(
#     request: Request,
#     category: str = Path(..., description="Category name to filter by"),
#     skip: int = Query(0, description="Number of records to skip"),
#     limit: int = Query(10, description="Number of records to return"),
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Get images filtered by category name"""
#     try:
#         # Query images with category filter (only active images and categories)
#         images = (
#             db.query(models.Image)
#             .join(models.ImageCategory)
#             .options(joinedload(models.Image.category))
#             .filter(
#                 models.ImageCategory.category == category,
#                 models.Image.deleted == False,
#                 models.ImageCategory.deleted == False
#             )
#             .offset(skip)
#             .limit(limit)
#             .all()
#         )

#         total = (
#             db.query(models.Image)
#             .join(models.ImageCategory)
#             .filter(
#                 models.ImageCategory.category == category,
#                 models.Image.deleted == False,
#                 models.ImageCategory.deleted == False
#             )
#             .count()
#         )

#         if not images:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"No images found in category '{category}'"
#             )

#         # Convert to Pydantic
#         serialized_data = [schemas.ImageWithCategory.from_orm(img) for img in images]

#         return {
#             "status": "success",
#             "result": {
#                 "count": total,
#                 "data": serialized_data
#             }
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=str(e)
#         )
# @router.get("/v1/image/byid/{image_id}", response_model=schemas.ImageWithCategory, dependencies=[require("read_image")])
# def get_image(
#     image_id: int,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Get image by ID"""
#     image = db.query(models.Image).filter(
#         models.Image.id == image_id,
#         models.Image.deleted == False
#     ).first()
    
#     if not image:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Image with id {image_id} not found"
#         )
    
#     return image


# @router.post("/v1/image/", 
#             status_code=status.HTTP_201_CREATED, 
#             response_model=schemas.ImageOut, 
#             dependencies=[require("create_image")])
# async def upload_image(
#     file: UploadFile = File(...),
#     name: Optional[str] = Form(None),
#     description: Optional[str] = Form(None),
#     category_id: Optional[int] = Form(None),
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Upload a new image"""
#     try:
#         # Validate file type
#         allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
#         if file.content_type not in allowed_types:
#             raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail=f"File type {file.content_type} not allowed. Allowed types: {', '.join(allowed_types)}"
#             )
        
#         # Validate category if provided
#         if category_id:
#             category = db.query(models.ImageCategory).filter(
#                 models.ImageCategory.id == category_id,
#                 models.ImageCategory.deleted == False
#             ).first()
            
#             if not category:
#                 raise HTTPException(
#                     status_code=status.HTTP_404_NOT_FOUND,
#                     detail=f"Image category with id {category_id} not found"
#                 )

#         # Save file
#         file_info = save_image_file(file)
        
#         if not file_info or not file_info.get("image_path"):
#             raise HTTPException(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 detail="Failed to save image file"
#             )

#         # Create image record with user tracking
#         new_image = models.Image(
#             name=name,
#             description=description,
#             category_id=category_id,
#             image_path=file_info["image_path"],
#             created_by_user_id=current_user.id,
#             updated_by_user_id=None
#         )
        
#         db.add(new_image)
#         db.commit()
#         db.refresh(new_image)

#         return new_image

#     except HTTPException:
#         raise
#     except Exception as e:
#         db.rollback()
#         # Clean up saved file on error
#         if 'file_info' in locals() and file_info.get("image_path"):
#             try:
#                 Path(file_info["image_path"]).unlink(missing_ok=True)
#             except Exception:
#                 pass
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Error uploading image: {str(e)}"
#         )


# @router.patch("/v1/image/{image_id}", 
#              response_model=schemas.ImageOut, 
#              dependencies=[require("update_image")])
# async def update_image(
#     image_id: int,
#     file: Optional[UploadFile] = File(None),
#     name: Optional[str] = Form(None),
#     description: Optional[str] = Form(None),
#     category_id: Optional[int] = Form(None),
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Update image information and optionally replace the file"""
#     try:
#         image = db.query(models.Image).filter(
#             models.Image.id == image_id,
#             models.Image.deleted == False
#         ).first()
        
#         if not image:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Image with id {image_id} not found"
#             )

#         # Update text fields
#         if name is not None:
#             image.name = name
#         if description is not None:
#             image.description = description
        
#         # Validate and update category if provided
#         if category_id is not None:
#             if category_id != image.category_id:
#                 category = db.query(models.ImageCategory).filter(
#                     models.ImageCategory.id == category_id,
#                     models.ImageCategory.deleted == False
#                 ).first()
                
#                 if not category:
#                     raise HTTPException(
#                         status_code=status.HTTP_404_NOT_FOUND,
#                         detail=f"Image category with id {category_id} not found"
#                     )
                
#                 image.category_id = category_id

#         # Handle file replacement
#         if file:
#             # Validate file type
#             allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
#             if file.content_type not in allowed_types:
#                 raise HTTPException(
#                     status_code=status.HTTP_400_BAD_REQUEST,
#                     detail=f"File type {file.content_type} not allowed"
#                 )
            
#             # Save new file
#             file_info = save_image_file(file)
            
#             # Delete old file
#             if image.image_path and os.path.exists(image.image_path):
#                 try:
#                     Path(image.image_path).unlink(missing_ok=True)
#                 except Exception as e:
#                     print(f"Warning: Couldn't delete old image: {e}")
            
#             # Update file path
#             image.image_path = file_info["image_path"]

#         # Track who updated
#         image.updated_by_user_id = current_user.id

#         db.commit()
#         db.refresh(image)

#         return image

#     except HTTPException:
#         raise
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Error updating image: {str(e)}"
#         )


# @router.delete("/v1/image/{image_id}", 
#               status_code=status.HTTP_200_OK, 
#               dependencies=[require("delete_image")])
# def delete_image(
#     image_id: int,
#     permanent: bool = False,
#     delete_file: bool = False,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Soft delete image (or permanent delete if superuser)"""
#     image = db.query(models.Image).filter(
#         models.Image.id == image_id
#     ).first()

#     if not image:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Image with id {image_id} not found"
#         )

#     if permanent and current_user.is_superuser:
#         # Permanent delete (hard delete) - only for superusers
#         # Optionally delete the physical file
#         if delete_file and image.image_path and os.path.exists(image.image_path):
#             try:
#                 Path(image.image_path).unlink(missing_ok=True)
#             except Exception as e:
#                 print(f"Warning: Couldn't delete image file: {e}")
        
#         db.delete(image)
#         db.commit()
#         return {"message": "Image permanently deleted"}
#     else:
#         # Soft delete with user tracking
#         image.soft_delete(user_id=current_user.id)
#         db.commit()
#         return {"message": "Image soft deleted successfully"}


# @router.post("/v1/image/{image_id}/restore", 
#             response_model=schemas.ImageOut, 
#             dependencies=[require("update_image")])
# def restore_image(
#     image_id: int,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     """Restore a soft-deleted image"""
#     image = db.query(models.Image).filter(
#         models.Image.id == image_id,
#         models.Image.deleted == True
#     ).first()

#     if not image:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail=f"Deleted image with id {image_id} not found"
#         )
    
#     # Check if the physical file still exists
#     if not os.path.exists(image.image_path):
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Cannot restore image. Physical file no longer exists."
#         )

#     image.restore()
#     image.updated_by_user_id = current_user.id
#     db.commit()
#     db.refresh(image)

#     return image






# app/api/routers/image.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request, Query
from fastapi import Path as PathParam  # FIXED: Alias to avoid conflict
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from pathlib import Path  # For file paths
import os
import shutil
from datetime import datetime
import uuid

from app import database, models, oauth2, schemas
from app.utils import paginate_data, filter_images
from app.dependencies.permission import require
from rest_framework import status


router = APIRouter(
    prefix="/api/images",
    tags=['Images']
)

# Configuration
UPLOAD_DIR = "static/images"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def save_image_file(file: UploadFile) -> dict:
    """Save uploaded image file and return file information"""
    try:
        # Generate unique filename
        file_extension = Path(file.filename).suffix  # Now uses pathlib.Path correctly
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        
        # Use forward slashes for URL paths (works on all platforms)
        save_path = f"{UPLOAD_DIR}/{unique_filename}"  # Use / not os.path.join
        
        # Create directories if needed
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # Save file
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        return {
            "image_path": save_path,  # Will be "static/images/uuid.jpg"
            "original_filename": file.filename,
            "file_size": os.path.getsize(save_path),
            "mime_type": file.content_type
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error saving file: {str(e)}"
        )


@router.get("/v1/image/", response_model=schemas.ImageListResponse, dependencies=[require("read_image")])
def get_images(
    request: Request,
    skip: int = 0,
    limit: int = 10,
    include_deleted: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user),
):
    """Get all images with pagination and filtering"""
    try:
        # Query based on include_deleted flag
        if include_deleted:
            query = models.Image.get_all_including_deleted(db)
        else:
            query = models.Image.get_active(db)
        
        # Apply filters directly without the problematic filter_images function
        query_params_dict = dict(request.query_params)
        
        # Apply common filters
        if 'category_id' in query_params_dict:
            category_id = query_params_dict['category_id']
            if isinstance(category_id, list):
                category_id = category_id[0]
            query = query.filter(models.Image.category_id == int(category_id))
        
        if 'name' in query_params_dict:
            name = query_params_dict['name']
            if isinstance(name, list):
                name = name[0]
            query = query.filter(models.Image.name.ilike(f"%{name}%"))
        
        if 'is_active' in query_params_dict:
            is_active = query_params_dict['is_active']
            if isinstance(is_active, list):
                is_active = is_active[0]
            is_active_bool = is_active.lower() in ['true', '1', 'yes']
            query = query.filter(models.Image.is_active == is_active_bool)
        
        # Add more filters as needed...
        
        total = query.count()
        images = query.offset(skip).limit(limit).all()

        # Convert ORM to Pydantic
        serialized_data = [schemas.ImageWithCategory.from_orm(img) for img in images]

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


@router.get("/v1/image/by/category/{category}", response_model=schemas.ImageListResponse, dependencies=[require("read_image")])
def get_images_by_category(
    request: Request,
    category: str = PathParam(..., description="Category name to filter by"),  # FIXED: Use PathParam alias
    skip: int = Query(0, description="Number of records to skip"),
    limit: int = Query(10, description="Number of records to return"),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Get images filtered by category name"""
    try:
        # Query images with category filter (only active images and categories)
        images = (
            db.query(models.Image)
            .join(models.ImageCategory)
            .options(joinedload(models.Image.category))
            .filter(
                models.ImageCategory.category == category,
                models.Image.deleted == False,
                models.ImageCategory.deleted == False
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

        total = (
            db.query(models.Image)
            .join(models.ImageCategory)
            .filter(
                models.ImageCategory.category == category,
                models.Image.deleted == False,
                models.ImageCategory.deleted == False
            )
            .count()
        )

        if not images:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No images found in category '{category}'"
            )

        # Convert to Pydantic
        serialized_data = [schemas.ImageWithCategory.from_orm(img) for img in images]

        return {
            "status": "success",
            "result": {
                "count": total,
                "data": serialized_data
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/v1/image/byid/{image_id}", response_model=schemas.ImageWithCategory, dependencies=[require("read_image")])
def get_image(
    image_id: int = PathParam(..., description="Image ID"),  # FIXED: Use PathParam alias
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Get image by ID"""
    image = db.query(models.Image).filter(
        models.Image.id == image_id,
        models.Image.deleted == False
    ).first()
    
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image with id {image_id} not found"
        )
    
    return image


@router.post("/v1/image/", 
            status_code=status.HTTP_201_CREATED, 
            response_model=schemas.ImageOut, 
            dependencies=[require("create_image")])
async def upload_image(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Upload a new image"""
    try:
        # Validate file type
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type {file.content_type} not allowed. Allowed types: {', '.join(allowed_types)}"
            )
        
        # Validate category if provided
        if category_id:
            category = db.query(models.ImageCategory).filter(
                models.ImageCategory.id == category_id,
                models.ImageCategory.deleted == False
            ).first()
            
            if not category:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Image category with id {category_id} not found"
                )

        # Save file
        file_info = save_image_file(file)
        
        if not file_info or not file_info.get("image_path"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save image file"
            )

        # Create image record with user tracking
        new_image = models.Image(
            name=name,
            description=description,
            category_id=category_id,
            image_path=file_info["image_path"],
            created_by_user_id=current_user.id,
            updated_by_user_id=None
        )
        
        db.add(new_image)
        db.commit()
        db.refresh(new_image)

        return new_image

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        # Clean up saved file on error
        if 'file_info' in locals() and file_info.get("image_path"):
            try:
                Path(file_info["image_path"]).unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading image: {str(e)}"
        )


@router.patch("/v1/image/{image_id}", 
             response_model=schemas.ImageOut, 
             dependencies=[require("update_image")])
async def update_image(
    image_id: int = PathParam(..., description="Image ID"),  # FIXED: Use PathParam alias
    file: Optional[UploadFile] = File(None),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Update image information and optionally replace the file"""
    try:
        image = db.query(models.Image).filter(
            models.Image.id == image_id,
            models.Image.deleted == False
        ).first()
        
        if not image:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Image with id {image_id} not found"
            )

        # Update text fields
        if name is not None:
            image.name = name
        if description is not None:
            image.description = description
        
        # Validate and update category if provided
        if category_id is not None:
            if category_id != image.category_id:
                category = db.query(models.ImageCategory).filter(
                    models.ImageCategory.id == category_id,
                    models.ImageCategory.deleted == False
                ).first()
                
                if not category:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Image category with id {category_id} not found"
                    )
                
                image.category_id = category_id

        # Handle file replacement
        if file:
            # Validate file type
            allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
            if file.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File type {file.content_type} not allowed"
                )
            
            # Save new file
            file_info = save_image_file(file)
            
            # Delete old file
            if image.image_path and os.path.exists(image.image_path):
                try:
                    Path(image.image_path).unlink(missing_ok=True)
                except Exception as e:
                    print(f"Warning: Couldn't delete old image: {e}")
            
            # Update file path
            image.image_path = file_info["image_path"]

        # Track who updated
        image.updated_by_user_id = current_user.id

        db.commit()
        db.refresh(image)

        return image

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating image: {str(e)}"
        )


@router.delete("/v1/image/{image_id}", 
              status_code=status.HTTP_200_OK, 
              dependencies=[require("delete_image")])
def delete_image(
    image_id: int = PathParam(..., description="Image ID"),  # FIXED: Use PathParam alias
    permanent: bool = False,
    delete_file: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Soft delete image (or permanent delete if superuser)"""
    image = db.query(models.Image).filter(
        models.Image.id == image_id
    ).first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image with id {image_id} not found"
        )

    if permanent and current_user.is_superuser:
        # Permanent delete (hard delete) - only for superusers
        # Optionally delete the physical file
        if delete_file and image.image_path and os.path.exists(image.image_path):
            try:
                Path(image.image_path).unlink(missing_ok=True)
            except Exception as e:
                print(f"Warning: Couldn't delete image file: {e}")
        
        db.delete(image)
        db.commit()
        return {"message": "Image permanently deleted"}
    else:
        # Soft delete with user tracking
        image.soft_delete(user_id=current_user.id)
        db.commit()
        return {"message": "Image soft deleted successfully"}


@router.post("/v1/image/{image_id}/restore", 
            response_model=schemas.ImageOut, 
            dependencies=[require("update_image")])
def restore_image(
    image_id: int = PathParam(..., description="Image ID"),  # FIXED: Use PathParam alias
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Restore a soft-deleted image"""
    image = db.query(models.Image).filter(
        models.Image.id == image_id,
        models.Image.deleted == True
    ).first()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deleted image with id {image_id} not found"
        )
    
    # Check if the physical file still exists
    if not os.path.exists(image.image_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot restore image. Physical file no longer exists."
        )

    image.restore()
    image.updated_by_user_id = current_user.id
    db.commit()
    db.refresh(image)

    return image