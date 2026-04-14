from pydantic import BaseModel, Field
from typing import Optional


class ChatSessionCreate(BaseModel):
    content_id: str
    discipline_id: Optional[str] = None
    mode: str = Field("socratic", pattern="^(socratic|free|guided)$")


class ChatMessageCreate(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1)


class SessionReviewCreate(BaseModel):
    session_id: str
    review: str = Field(..., min_length=1)
    rating: Optional[int] = Field(None, ge=1, le=5)


class ReviewReplyCreate(BaseModel):
    reply: str = Field(..., min_length=1)
