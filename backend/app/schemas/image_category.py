# # schemas/image_category.py

# from typing import Optional, List
# from pydantic import BaseModel

# # ✅ Shared base schema for creation/update input
# class ImageCategoryBase(BaseModel):
#     category: str

# # ✅ Schema used only for creation input
# class ImageCategoryCreate(ImageCategoryBase):
#     created_by_user_id: Optional[int] = None

#     class Config:
#         extra = "forbid"

# # ✅ Schema used only for update input
# class ImageCategoryUpdate(BaseModel):
#     category: Optional[str] = None
#     updated_by_user_id: Optional[int] = None

#     class Config:
#         extra = "forbid"

# # ✅ Schema for nested image objects in response
# class ImageOut(BaseModel):
#     id: int
#     image_url: str

#     class Config:
#         from_attributes = True

# # ✅ Response schema (renamed for clarity)
# class ImageCategoryOut(ImageCategoryBase):
#     id: int
#     created_by_user_id: Optional[int] = None
#     updated_by_user_id: Optional[int] = None

#     class Config:
#         from_attributes = True

# # ✅ Full response schema for a single image category (Optional)
# class ImageCategory(ImageCategoryOut):
#     pass

# # ✅ Schema for paginated list
# class PaginatedImageCategory(BaseModel):
#     count: int
#     data: List[ImageCategory]

# # ✅ Wrapper for API responses
# class ImageCategoryListResponse(BaseModel):
#     status: str
#     result: PaginatedImageCategory



# app/schemas/image_category.py
from pydantic import BaseModel, Field
from typing import Optional, List
from app.schemas.base import TimeUserStampSchema


class ImageCategoryBase(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)


class ImageCategoryCreate(ImageCategoryBase):
    class Config:
        extra = "forbid"


class ImageCategoryUpdate(BaseModel):
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    
    class Config:
        extra = "forbid"


class ImageCategoryOut(ImageCategoryBase, TimeUserStampSchema):
    """Full response with all mixin fields"""
    id: int
    
    class Config:
        from_attributes = True


# ✅ Basic image info for nested responses
class ImageBasicForCategory(BaseModel):
    """Basic image info for nested category responses"""
    id: int
    name: Optional[str] = None
    image_path: str
    
    class Config:
        from_attributes = True


class ImageCategoryWithImages(ImageCategoryOut):
    """Category with nested images"""
    images: List[ImageBasicForCategory] = []
    
    class Config:
        from_attributes = True


# ✅ Category with stats
class ImageCategoryWithStats(ImageCategoryOut):
    """Category with image count"""
    image_count: int = 0
    
    class Config:
        from_attributes = True


class PaginatedImageCategories(BaseModel):
    count: int
    data: List[ImageCategoryOut]


class PaginatedImageCategoriesWithImages(BaseModel):
    count: int
    data: List[ImageCategoryWithImages]


class ImageCategoryListResponse(BaseModel):
    status: str
    result: PaginatedImageCategories


class ImageCategoryListWithImagesResponse(BaseModel):
    status: str
    result: PaginatedImageCategoriesWithImages