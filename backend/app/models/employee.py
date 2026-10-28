# app/models/employee.py
from sqlalchemy import Column, ForeignKey, Integer, String, Date, Float
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from app.database import Base
from app.models.mixins import TimeUserStampMixin


class Employee(TimeUserStampMixin, Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    phone_number = Column(String(20))
    hire_date = Column(Date, nullable=False)
    job_title = Column(String(100), nullable=False)
    salary = Column(Float, nullable=False)
    department_id = Column(Integer, nullable=True)
    rank_id = Column(Integer, nullable=True)

    # Foreign key to User
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=True)

    @hybrid_property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    # User relationship (one-to-one)
    user = relationship(
        "User",
        back_populates="employee",
        uselist=False,
        foreign_keys=[user_id]
    )

    # Override UserStampMixin back_populates
    creator = relationship("User", foreign_keys=[created_by_user_id], back_populates="created_employees")
    updater = relationship("User", foreign_keys=[updated_by_user_id], back_populates="updated_employees")
    deleter = relationship("User", foreign_keys=[deleted_by_user_id], back_populates="deleted_employees")