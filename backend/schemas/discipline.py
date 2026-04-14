from pydantic import BaseModel, Field
from typing import Optional


class DisciplineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=50)
    department: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None


class DisciplineUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    code: Optional[str] = Field(None, max_length=50)
    department: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    image_url: Optional[str] = None


class TeacherAssignment(BaseModel):
    teacher_id: str


class StudentAssignment(BaseModel):
    student_id: str


class StudentBatchAssignment(BaseModel):
    student_ids: list[str]
