from pydantic import BaseModel, Field
from typing import Optional


class CourseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field("", max_length=5000)
    instructor_id: Optional[str] = None
    discipline_id: Optional[str] = None
    image_url: Optional[str] = None


class ChapterCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = Field("", max_length=5000)
    order: int = Field(0, ge=0)


class ContentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    type: str = Field(..., min_length=1, max_length=20)
    content_url: Optional[str] = None
    text_content: Optional[str] = Field(None, max_length=100000)
    order: int = Field(0, ge=0)


class ContentUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=300)
    type: Optional[str] = Field(None, max_length=20)
    content_url: Optional[str] = None
    text_content: Optional[str] = None
    audio_url: Optional[str] = None
    text_url: Optional[str] = None
    order: Optional[int] = None


class QuestionCreate(BaseModel):
    question: str = Field(..., min_length=1)
    options: list[str] = Field(default_factory=list)
    correct_answer: str = ""
    explanation: Optional[str] = None
    difficulty: Optional[str] = Field(None, pattern="^(easy|medium|hard)$")
    status: str = Field("active", pattern="^(active|draft|archived)$")


class QuestionUpdate(BaseModel):
    question: Optional[str] = None
    options: Optional[list[str]] = None
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    difficulty: Optional[str] = None
    status: Optional[str] = None


class QuestionBatchCreate(BaseModel):
    questions: list[QuestionCreate]
