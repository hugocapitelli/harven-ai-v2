from pydantic import BaseModel, Field
from typing import Optional


class ChatSessionCreate(BaseModel):
    """Create-or-get payload for a chat session.

    ``user_id`` (TPP-2): the field is accepted for backwards compatibility with
    older clients, but it is **never** the source of truth for ownership. The
    session owner is always derived from the authenticated ``current_user`` in the
    route; a forged ``user_id`` is rejected by ``authz.assert_owner_or_role`` and
    never reaches any SELECT/INSERT/UPSERT. Do not use it for authorization.
    """
    user_id: Optional[str] = None
    content_id: str
    chapter_id: Optional[str] = None
    course_id: Optional[str] = None
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
