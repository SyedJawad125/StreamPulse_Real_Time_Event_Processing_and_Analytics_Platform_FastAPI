# # app/models/image.py

# from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
# from sqlalchemy.orm import relationship
# from app.database import Base
# from datetime import datetime

# class Image(Base):
#     __tablename__ = "images"

#     id = Column(Integer, primary_key=True, index=True)
#     name = Column(String(30), nullable=True)
#     description = Column(Text, nullable=True)
#     image_path = Column(String(255), nullable=False) 
#     upload_date = Column(DateTime, default=datetime.utcnow, nullable=False)

#     category_id = Column(Integer, ForeignKey("imagecategories.id"), nullable=True)
#     created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
#     updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

#     # Relationships
#     category = relationship("ImageCategory", back_populates="images", lazy="joined")
#     creator = relationship("User", foreign_keys=[created_by_user_id], backref="images_created")
#     updater = relationship("User", foreign_keys=[updated_by_user_id], backref="images_updated")





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


class Image(TimeUserStampMixin, Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(30), nullable=True)
    description = Column(Text, nullable=True)
    image_path = Column(String(255), nullable=False)

    # Category relationship
    category_id = Column(Integer, ForeignKey("imagecategories.id"), nullable=True)
    category = relationship("ImageCategory", back_populates="images", lazy="joined")