# from sqlalchemy import Column, Integer, String, ForeignKey
# from sqlalchemy.orm import relationship
# from app.database import Base

# class ImageCategory(Base):
#     __tablename__ = "imagecategories"

#     id = Column(Integer, primary_key=True, index=True)
#     category = Column(String(50), nullable=False)
    
#     # Foreign Keys
#     created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
#     updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

#     # Relationships
#     creator = relationship("User", foreign_keys=[created_by_user_id], backref="categories_created")
#     updater = relationship("User", foreign_keys=[updated_by_user_id], backref="categories_updated")
    
#     # Relationship with Images
#     images = relationship("Image", back_populates="category")