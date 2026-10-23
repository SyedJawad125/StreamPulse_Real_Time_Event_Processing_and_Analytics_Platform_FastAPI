# from pydantic import BaseModel, EmailStr
# from datetime import date
# from typing import List, Optional

# class EmployeeBase(BaseModel):
#     first_name: str
#     last_name: str
#     email: EmailStr
#     phone_number: Optional[str] = None
#     hire_date: date
#     job_title: str
#     salary: float
    

# class EmployeeCreate(EmployeeBase):
#    class Config:
#         extra = "forbid"


# class Employee(EmployeeBase):
#     id: int
    
#     class Config:
#         from_attributes = True  # Previously called orm_mode in Pydantic v1

# class PaginatedEmployees(BaseModel):
#     count: int
#     data: List[Employee]

# # ✅ Add this for final API response
# class EmployeeListResponse(BaseModel):
#     status: str
#     result: PaginatedEmployees

# class EmployeeUpdate(BaseModel):
#     first_name: Optional[str] = None
#     last_name: Optional[str] = None
#     email: Optional[EmailStr] = None
#     phone_number: Optional[str] = None
#     hire_date: Optional[date] = None
#     job_title: Optional[str] = None
#     salary: Optional[float] = None
#     class Config:
#         extra = "forbid"



# app/schemas/employee.py
from pydantic import BaseModel, EmailStr, Field
from datetime import date
from typing import Optional
from app.schemas.base import TimeUserStampSchema


class EmployeeBase(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    phone_number: Optional[str] = Field(None, max_length=20)
    hire_date: date
    job_title: str = Field(..., min_length=1, max_length=100)
    salary: float = Field(..., gt=0)


class EmployeeCreate(EmployeeBase):
    user_id: Optional[int] = None  # ✅ Added to link employee to user
    
    class Config:
        extra = "forbid"


class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=50)
    last_name: Optional[str] = Field(None, min_length=1, max_length=50)
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = Field(None, max_length=20)
    hire_date: Optional[date] = None
    job_title: Optional[str] = Field(None, min_length=1, max_length=100)
    salary: Optional[float] = Field(None, gt=0)
    user_id: Optional[int] = None  # ✅ Added
    
    class Config:
        extra = "forbid"


class EmployeeOut(EmployeeBase, TimeUserStampSchema):
    id: int
    name: str
    user_id: Optional[int] = None  # ✅ Added to expose the relationship
    
    class Config:
        from_attributes = True


# ✅ NEW: Employee with user details
class UserBasicForEmployee(BaseModel):
    """Basic user info for nested employee responses"""
    id: int
    username: Optional[str] = None
    email: EmailStr
    is_active: bool
    
    class Config:
        from_attributes = True


class EmployeeWithUser(EmployeeOut):
    """Employee with user details"""
    user: Optional[UserBasicForEmployee] = None
    
    class Config:
        from_attributes = True


class PaginatedEmployees(BaseModel):
    count: int
    data: list[EmployeeOut]


class EmployeeListResponse(BaseModel):
    status: str
    result: PaginatedEmployees


# ✅ NEW: For detailed employee list with user info
class PaginatedEmployeesWithUser(BaseModel):
    count: int
    data: list[EmployeeWithUser]


class EmployeeListWithUserResponse(BaseModel):
    status: str
    result: PaginatedEmployeesWithUser