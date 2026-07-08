from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    ra: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=6)
    role: str = Field("STUDENT", pattern="^(ADMIN|INSTRUCTOR|STUDENT)$")
    title: Optional[str] = None
    bio: Optional[str] = None


# NOTE: this UserUpdate is dead code — not imported by main.py, which defines
# its own UserUpdate (with the `status` field) inline. Left as-is per BUG-1
# scope (out of scope to refactor/consolidate imports here).
class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    email: Optional[EmailStr] = None
    role: Optional[str] = Field(None, pattern="^(ADMIN|INSTRUCTOR|STUDENT)$")
    title: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    ra: str
    role: str
    avatar_url: Optional[str] = None
    title: Optional[str] = None
    bio: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserBatchCreate(BaseModel):
    users: list[UserCreate]
