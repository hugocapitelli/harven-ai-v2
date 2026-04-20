from pydantic import BaseModel, Field
from typing import Optional


class QuestionGenerationRequest(BaseModel):
    content_id: Optional[str] = None
    chapter_content: str = ""
    chapter_title: str = ""
    learning_objective: str = ""
    difficulty: str = "intermediario"
    max_questions: int = Field(3, ge=1, le=20)


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
