# from typing import Optional
# from pydantic import BaseModel, Field
# from datetime import datetime
# from .image_category import ImageCategoryOut  # ✅ Correct import


# class ImageBase(BaseModel):
#     name: Optional[str] = Field(None, max_length=30)
#     description: Optional[str] = Field(None, max_length=500)
#     category_id: Optional[int] = None

# class ImageCreate(ImageBase):
#     # Required fields for creation
#     created_by_user_id: int
#     updated_by_user_id: int
#     image_path: str
    
#     # Optional file metadata that should come from the uploaded file
#     original_filename: Optional[str] = None
#     file_size: Optional[int] = None
#     mime_type: Optional[str] = None

# class ImageUpdate(ImageBase):
#     image_path: Optional[str] = None
#     original_filename: Optional[str] = None
#     file_size: Optional[int] = None
#     mime_type: Optional[str] = None
#     updated_by_user_id: Optional[int] = None


# class ImageOut(ImageBase):
#     id: int
#     image_path: str  # Make sure this is not optional in the response
#     upload_date: datetime
#     created_by_user_id: int  # Changed from Optional to required
#     updated_by_user_id: Optional[int] = None  # Keep as Optional
#     # category: Optional[ImageCategory] = None
#     category: Optional[ImageCategoryOut] = None  # Use the response schema

#     class Config:
#         from_attributes = True

# class PaginatedImages(BaseModel):
#     count: int
#     data: list[ImageOut]

# class ImageListResponse(BaseModel):
#     status: str
#     result: PaginatedImages


# app/schemas/image.py
from pydantic import BaseModel, Field
from typing import Optional, TYPE_CHECKING
from app.schemas.base import TimeUserStampSchema


class ImageBase(BaseModel):
    name: Optional[str] = Field(None, max_length=30)
    description: Optional[str] = Field(None, max_length=500)
    category_id: Optional[int] = None


class ImageCreate(ImageBase):
    """Schema for image creation"""
    pass
    
    class Config:
        extra = "forbid"


class ImageUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=30)
    description: Optional[str] = Field(None, max_length=500)
    category_id: Optional[int] = None
    
    class Config:
        extra = "forbid"


class ImageOut(ImageBase, TimeUserStampSchema):
    """Full image response with all mixin fields"""
    id: int
    image_path: str
    
    class Config:
        from_attributes = True


# Forward reference setup to avoid circular imports
if TYPE_CHECKING:
    from app.schemas.image_category import ImageCategoryOut


class ImageCategoryBasic(BaseModel):
    """Basic category info for nested responses"""
    id: int
    category: str
    
    class Config:
        from_attributes = True


class ImageWithCategory(ImageOut):
    """Image with category details"""
    category: Optional[ImageCategoryBasic] = None
    
    class Config:
        from_attributes = True


class PaginatedImages(BaseModel):
    count: int
    data: list[ImageOut]


class PaginatedImagesWithCategory(BaseModel):
    count: int
    data: list[ImageWithCategory]


class ImageListResponse(BaseModel):
    status: str
    result: PaginatedImages


class ImageListWithCategoryResponse(BaseModel):
    status: str
    result: PaginatedImagesWithCategory


class ImageUploadResponse(BaseModel):
    """Response after successful image upload"""
    status: str
    message: str
    data: ImageOut