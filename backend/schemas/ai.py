from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional


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


# ---------------------------------------------------------------------------
# AI-HARD-1: response_model (SUPERSET) for POST /api/ai/analyst/detect.
#
# Mirrors the exact dict returned by ``AIService.detect_ai_content`` (both the
# LLM-validated path and the heuristic/mock fallback share one return shape).
# Every nested model sets ``extra='ignore'`` so a richer LLM/heuristic payload
# never breaks serialization, and every field the frontend consumes is declared
# explicitly so FastAPI never silently filters it out. Conservative by design:
# a missing field = broken frontend, so this is a superset, not a tight schema.
# ---------------------------------------------------------------------------
class AIDetectionAnalysis(BaseModel):
    """The ``ai_detection`` sub-object."""

    model_config = ConfigDict(extra="ignore")

    probability: float
    confidence: str
    verdict: str
    indicators: List[Dict[str, Any]] = Field(default_factory=list)
    flag: Optional[str] = None


class AIDetectionTextMetrics(BaseModel):
    """The ``metrics.text`` sub-object."""

    model_config = ConfigDict(extra="ignore")

    message_length_chars: int
    message_length_words: int
    sentence_count: int
    has_question: bool


class AIDetectionMetrics(BaseModel):
    """The ``metrics`` sub-object."""

    model_config = ConfigDict(extra="ignore")

    text: AIDetectionTextMetrics


class AIDetectionResponse(BaseModel):
    """Stable output contract for ``POST /api/ai/analyst/detect``.

    Superset of ``detect_ai_content``'s return: declares every top-level and
    nested field the route emits today (LLM path + heuristic/mock fallback),
    tolerating extra fields via ``extra='ignore'`` so the contract never drops
    data the frontend relies on.
    """

    model_config = ConfigDict(extra="ignore")

    analysis_id: str
    timestamp: str
    ai_detection: AIDetectionAnalysis
    metrics: AIDetectionMetrics
    flags: List[str] = Field(default_factory=list)
    observations: List[Any] = Field(default_factory=list)
    recommendation: str
