# app/models/image_category.py
# Note: ImageCategory model is now defined in app/models/image.py to avoid duplication
# This file is kept for backwards compatibility - import from image.py instead
from app.models.image import ImageCategory  # noqa: F401

__all__ = ["ImageCategory"]