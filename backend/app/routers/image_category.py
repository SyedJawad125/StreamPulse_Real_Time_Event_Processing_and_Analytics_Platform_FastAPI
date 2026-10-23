# from fastapi import APIRouter, Depends, status, Request, HTTPException
# from sqlalchemy.orm import Session
# from typing import Any, List, Optional

# from app import database, models, oauth2
# from app.utils import paginate_data
# from app.utils import filter_image_categories
# from app.schemas.image_category import (
#     ImageCategory,
#     ImageCategoryCreate,
#     ImageCategoryUpdate,
#     ImageCategoryListResponse,
# )
# from app.dependencies.permission import require
# from math import ceil

# router = APIRouter(
#     prefix="/image_categories",
#     tags=['ImageCategory']
# )


# @router.get("/", response_model=ImageCategoryListResponse, dependencies=[require("read_image_category")])
# def get_image_categories(
#     request: Request,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user),
#     page: int = 1,
#     limit: int = 10
# ):
#     try:
#         query = db.query(models.ImageCategory)
#         query = filter_image_categories(request.query_params, query)
        
#         # Get total count before pagination
#         total_count = query.count()
        
#         # Apply pagination
#         offset = (page - 1) * limit
#         data = query.offset(offset).limit(limit).all()
        
#         serialized_data = [ImageCategory.from_orm(item) for item in data]

#         return {
#             "status": "SUCCESSFUL",
#             "result": {
#                 "count": total_count,
#                 "total_pages": ceil(total_count / limit),
#                 "current_page": page,
#                 "data": serialized_data
#             }
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post("/", status_code=status.HTTP_201_CREATED, response_model=ImageCategory, dependencies=[require("create_image_category")])
# def create_image_category(
#     image_category: ImageCategoryCreate,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ) -> Any:
#     try:
#         category_data = image_category.dict()
#         category_data["created_by_user_id"] = current_user.id

#         new_category = models.ImageCategory(**category_data)
#         db.add(new_category)
#         db.commit()
#         db.refresh(new_category)

#         return new_category
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.get("/{id}", response_model=ImageCategory, dependencies=[require("read_image_category")])
# def get_image_category(
#     id: int,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     category = db.query(models.ImageCategory).filter(models.ImageCategory.id == id).first()
#     if not category:
#         raise HTTPException(status_code=404, detail=f"Image Category with id {id} not found")
#     return category


# @router.patch("/{id}", response_model=ImageCategory, dependencies=[require("update_image_category")])
# def patch_update_image_category(
#     id: int,
#     updated_category: ImageCategoryUpdate,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     category_instance = db.query(models.ImageCategory).filter(models.ImageCategory.id == id).first()

#     if not category_instance:
#         raise HTTPException(status_code=404, detail=f"Image Category with id {id} not found")

#     update_data = updated_category.dict(exclude_unset=True)
#     update_data["updated_by_user_id"] = current_user.id

#     for key, value in update_data.items():
#         setattr(category_instance, key, value)

#     db.commit()
#     db.refresh(category_instance)

#     return category_instance


# @router.delete("/{id}", status_code=status.HTTP_200_OK, dependencies=[require("delete_image_category")])
# def delete_image_category(
#     id: int,
#     db: Session = Depends(database.get_db),
#     current_user: models.User = Depends(oauth2.get_current_user)
# ):
#     category_query = db.query(models.ImageCategory).filter(models.ImageCategory.id == id)
#     category = category_query.first()

#     if not category:
#         raise HTTPException(status_code=404, detail=f"Image Category with id {id} not found")

#     category_query.delete(synchronize_session=False)
#     db.commit()

#     return {"message": "Image Category deleted successfully"}






# app/api/routers/image_category.py
from fastapi import APIRouter, Depends, status, Request, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app import database, models, oauth2, schemas
from app.utils import paginate_data, filter_image_categories
from app.dependencies.permission import require


router = APIRouter(
    prefix="/api/categories",
    tags=['Image Categories']
)


@router.get("/v1/category/", response_model=schemas.ImageCategoryListResponse, dependencies=[require("read_image_category")])
def get_image_categories(
    request: Request,
    skip: int = 0,
    limit: int = 10,
    include_deleted: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user),
):
    """Get all image categories with pagination and filtering"""
    try:
        # Query based on include_deleted flag
        if include_deleted:
            query = models.ImageCategory.get_all_including_deleted(db)
        else:
            query = models.ImageCategory.get_active(db)
        
        # Apply filters
        query = filter_image_categories(request.query_params, query)
        
        total = query.count()
        categories = query.offset(skip).limit(limit).all()

        # Convert ORM to Pydantic
        serialized_data = [schemas.ImageCategoryOut.from_orm(cat) for cat in categories]

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


@router.get("/v1/category/{id}", response_model=schemas.ImageCategoryOut, dependencies=[require("read_image_category")])
def get_image_category(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Get image category by ID"""
    category = db.query(models.ImageCategory).filter(
        models.ImageCategory.id == id,
        models.ImageCategory.deleted == False
    ).first()
    
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image category with id {id} not found"
        )
    
    return category


@router.post("/v1/category/", 
            status_code=status.HTTP_201_CREATED, 
            response_model=schemas.ImageCategoryOut, 
            dependencies=[require("create_image_category")])
def create_image_category(
    category: schemas.ImageCategoryCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Create a new image category"""
    try:
        # Create category with user tracking
        category_data = category.dict()
        new_category = models.ImageCategory(
            **category_data,
            created_by_user_id=current_user.id,
            updated_by_user_id=None  # Explicitly set to None
        )
        
        db.add(new_category)
        db.commit()
        db.refresh(new_category)

        return new_category

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating image category: {str(e)}"
        )


@router.patch("/v1/category/{id}", 
             response_model=schemas.ImageCategoryOut, 
             dependencies=[require("update_image_category")])
def update_image_category(
    id: int,
    category_update: schemas.ImageCategoryUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Update image category information"""
    try:
        category = db.query(models.ImageCategory).filter(
            models.ImageCategory.id == id,
            models.ImageCategory.deleted == False
        ).first()

        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Image category with id {id} not found"
            )

        update_data = category_update.dict(exclude_unset=True)

        # Update fields
        for key, value in update_data.items():
            setattr(category, key, value)
        
        # Track who updated
        category.updated_by_user_id = current_user.id

        db.commit()
        db.refresh(category)

        return category

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating image category: {str(e)}"
        )


@router.delete("/v1/category/{id}", 
              status_code=status.HTTP_200_OK, 
              dependencies=[require("delete_image_category")])
def delete_image_category(
    id: int,
    permanent: bool = False,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Soft delete image category (or permanent delete if superuser)"""
    category = db.query(models.ImageCategory).filter(
        models.ImageCategory.id == id
    ).first()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image category with id {id} not found"
        )

    # Check if category has active images
    active_images_count = db.query(models.Image).filter(
        models.Image.category_id == id,
        models.Image.deleted == False
    ).count()
    
    if active_images_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete category. It has {active_images_count} active image(s)."
        )

    if permanent and current_user.is_superuser:
        # Permanent delete (hard delete) - only for superusers
        db.delete(category)
        db.commit()
        return {"message": "Image category permanently deleted"}
    else:
        # Soft delete with user tracking
        category.soft_delete(user_id=current_user.id)
        db.commit()
        return {"message": "Image category soft deleted successfully"}


@router.post("/{id}/restore", 
            response_model=schemas.ImageCategoryOut, 
            dependencies=[require("update_image_category")])
def restore_image_category(
    id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(oauth2.get_current_user)
):
    """Restore a soft-deleted image category"""
    category = db.query(models.ImageCategory).filter(
        models.ImageCategory.id == id,
        models.ImageCategory.deleted == True
    ).first()

    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deleted image category with id {id} not found"
        )

    category.restore()
    category.updated_by_user_id = current_user.id
    db.commit()
    db.refresh(category)

    return category