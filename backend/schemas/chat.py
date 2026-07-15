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
    # SOC-1: the "Pergunta para Reflexão" the student committed to. Written ONCE
    # on session creation; on resume the stored value is never overwritten
    # (first-write-wins), so the frontend can derive a durable lock from it.
    initial_question_text: Optional[str] = None


class ChatMessageCreate(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1)


class SessionReviewCreate(BaseModel):
    """Per-session teacher review payload.

    GRD-1: the rating scale is 0–10 (matching ``session_reviews.rating`` and the
    gradebook aggregation), NOT 1–5. The live review routes use the equivalent
    model declared inline in ``routes_admin.py`` (``rating`` 0–10 + ``feedback``);
    this schema is kept in sync with that contract so the two never diverge again.
    """
    session_id: str
    feedback: Optional[str] = None
    rating: Optional[float] = Field(None, ge=0, le=10)


class ReviewReplyCreate(BaseModel):
    reply: str = Field(..., min_length=1)
