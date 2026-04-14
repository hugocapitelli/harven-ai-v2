from pydantic import BaseModel, Field
from typing import Optional


class QuestionGenerationRequest(BaseModel):
    content_id: str
    count: int = Field(5, ge=1, le=20)
    difficulty: Optional[str] = Field(None, pattern="^(easy|medium|hard|mixed)$")
    language: str = "pt-BR"


class SocraticDialogueRequest(BaseModel):
    content_id: str
    user_message: str = Field(..., min_length=1)
    session_id: Optional[str] = None


class AIDetectionRequest(BaseModel):
    text: str = Field(..., min_length=10)


class EditResponseRequest(BaseModel):
    question_id: str
    response: str = Field(..., min_length=1)
    feedback: Optional[str] = None


class ValidateResponseRequest(BaseModel):
    question_id: str
    student_answer: str = Field(..., min_length=1)
