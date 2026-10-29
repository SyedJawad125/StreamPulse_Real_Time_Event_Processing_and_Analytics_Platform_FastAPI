# app/models/image.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.mixins import TimeUserStampMixin


class ImageCategory(TimeUserStampMixin, Base):
    __tablename__ = "imagecategories"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False)

    # Relationship with Images
    images = relationship("Image", back_populates="category")

    # Override UserStampMixin back_populates to use underscores
    creator = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_image_categories")
    updater = relationship("User", foreign_keys=[updated_by_user_id], back_populates="updated_image_categories")
    deleter = relationship("User", foreign_keys=[deleted_by_user_id], back_populates="deleted_image_categories")


class Image(TimeUserStampMixin, Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(30), nullable=True)
    description = Column(Text, nullable=True)
    image_path = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    bulletsdescription = Column(Text, nullable=True)

    # Category relationship
    category_id = Column(Integer, ForeignKey("imagecategories.id"), nullable=True)
    category = relationship("ImageCategory", back_populates="images", lazy="joined")

    # Override UserStampMixin back_populates
    creator = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_images")
    updater = relationship("User", foreign_keys=[updated_by_user_id], back_populates="updated_images")
    deleter = relationship("User", foreign_keys=[deleted_by_user_id], back_populates="deleted_images")