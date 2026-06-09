"""AI output contracts — validated Pydantic v2 models for LLM responses.

Story AI-HARD-0 (EPIC-AI). This module is the *contract layer* for the LLM
output of the AI-content detector (AnalystOS) and the quality-gate Tester
(TesterOS). It is **purely additive**: it introduces validation/coercion models
plus a safe JSON parser. It does **not** touch any production call-site, so the
runtime blast radius of this story is nil.

Future consumers (AI-HARD-1/2/4/5) will import these models to harden the
existing call-sites that today read LLM JSON verbatim:

* ``AIDetectionResult`` hardens ``detect_ai_content`` (bug #29/#30) — today
  ``probability``/``confidence``/``verdict`` are read with ``parsed.get(...)``
  and compared (``probability > 0.70``) outside the try/except, so a string,
  ``None``, or an out-of-range number leaks an HTTP 500 or a nonsense flag.
* ``TesterVerdict`` hardens ``validate_response`` (bug #32) — today a bare
  ``except (json.JSONDecodeError, Exception)`` fabricates an ``APPROVED`` verdict
  on any parse/transport failure (fail-open).

The enums mirror the system prompts in ``ai_service.py``:
``ANALYST_PROMPT`` (``verdict``/``confidence`` for the detector) and
``TESTER_PROMPT`` (``verdict`` for the Tester). Keep these in sync if the prompt
contracts ever change.

Stable surface for AI-HARD-1..5 (do not break field names / enum values):
``AIDetectionResult``, ``TesterVerdict``, ``_parse_model_json``,
plus the enums ``VerdictEnum``, ``ConfidenceEnum``, ``TesterVerdictEnum``.
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Optional, Type, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums — mirror the LLM output contracts declared in ai_service.py prompts.
# ---------------------------------------------------------------------------
# Detector (AnalystOS) — see ANALYST_PROMPT in ai_service.py:
#   {"probability": 0.0-1.0, "confidence": "low|medium|high",
#    "verdict": "likely_human|uncertain|likely_ai", ...}
class VerdictEnum(str, Enum):
    """Detector verdict enum — mirrors ANALYST_PROMPT (ai_service.py)."""

    LIKELY_HUMAN = "likely_human"
    UNCERTAIN = "uncertain"
    LIKELY_AI = "likely_ai"


class ConfidenceEnum(str, Enum):
    """Detector confidence enum — mirrors ANALYST_PROMPT (ai_service.py)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Tester (TesterOS) — see TESTER_PROMPT in ai_service.py:
#   {"verdict": "APPROVED|NEEDS_REVISION|REJECTED", "score": 0.0-1.0, ...}
class TesterVerdictEnum(str, Enum):
    """Tester verdict enum — mirrors TESTER_PROMPT (ai_service.py)."""

    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Shared coercion helpers.
# ---------------------------------------------------------------------------
def _coerce_to_float(value: object) -> object:
    """Coerce a numeric string into a float (``'0.8'`` -> ``0.8``).

    Runs as a ``mode='before'`` validator so it sees the raw LLM value. Numeric
    strings are parsed via ``float()``; anything else is passed through
    unchanged so Pydantic's own type validation can reject it (or so ``None``
    can be handled by an ``Optional`` field). A non-numeric string raises
    ``ValueError`` here, which Pydantic surfaces as a ``ValidationError``.
    """
    if isinstance(value, str):
        return float(value)
    return value


def _clamp_unit_interval(value: float) -> float:
    """Clamp a float to the closed unit interval ``[0.0, 1.0]``.

    ``1.5`` -> ``1.0`` (no spurious flag against the student) and ``-0.2`` ->
    ``0.0``. Applied after type validation, so ``value`` is already a float.
    """
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


# ---------------------------------------------------------------------------
# Detector contract (AnalystOS) — bug #29 / #30.
# ---------------------------------------------------------------------------
class AIDetectionResult(BaseModel):
    """Validated contract for the AI-content detector output.

    Hardens the verbatim reads at ``detect_ai_content`` (bug #29/#30). Coerces a
    numeric-string ``probability`` to ``float``, clamps it to ``[0.0, 1.0]``, and
    restricts ``verdict``/``confidence`` to their enums (out-of-enum ->
    ``ValidationError``). Extra LLM fields (e.g. ``indicators``) are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    probability: float
    verdict: VerdictEnum
    confidence: ConfidenceEnum

    @field_validator("probability", mode="before")
    @classmethod
    def _coerce_probability(cls, value: object) -> object:
        # str -> float coercion before type validation ('0.8' -> 0.8).
        return _coerce_to_float(value)

    @field_validator("probability", mode="after")
    @classmethod
    def _clamp_probability(cls, value: float) -> float:
        # Clamp to [0, 1] after the value is a validated float (1.5 -> 1.0).
        return _clamp_unit_interval(value)


# ---------------------------------------------------------------------------
# Tester contract (TesterOS) — bug #32.
# ---------------------------------------------------------------------------
class TesterVerdict(BaseModel):
    """Validated contract for the Tester (quality-gate) output.

    Hardens the fail-open path at ``validate_response`` (bug #32). Restricts
    ``verdict`` to its enum (out-of-enum -> ``ValidationError``); ``score`` is
    optional and, when present, is coerced from a numeric string and clamped to
    ``[0.0, 1.0]``. Extra LLM fields (e.g. ``criteria``) are ignored so a richer
    payload never breaks validation.
    """

    # Not a test class — tell pytest to skip it (the name matches pytest's
    # `Test*`/`*Tester*` collection heuristic). Pydantic v2 treats this as a
    # plain class attribute, not a model field.
    __test__ = False

    model_config = ConfigDict(extra="ignore")

    verdict: TesterVerdictEnum
    score: Optional[float] = None

    @field_validator("score", mode="before")
    @classmethod
    def _coerce_score(cls, value: object) -> object:
        # str -> float coercion before type validation ('0.8' -> 0.8); None
        # is passed through (score is Optional).
        if value is None:
            return None
        return _coerce_to_float(value)

    @field_validator("score", mode="after")
    @classmethod
    def _clamp_score(cls, value: Optional[float]) -> Optional[float]:
        # Clamp to [0, 1] only when a score is present.
        if value is None:
            return None
        return _clamp_unit_interval(value)


# ---------------------------------------------------------------------------
# Safe JSON parser — the single "bad JSON -> None" decision point.
# ---------------------------------------------------------------------------
_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _parse_model_json(raw: str, model_cls: Type[_ModelT]) -> Optional[_ModelT]:
    """Parse ``raw`` JSON into a validated ``model_cls`` instance, or ``None``.

    This is the **only** place that decides "bad JSON -> None". It runs
    ``json.loads`` followed by ``model_cls.model_validate`` and returns the
    validated model on success. Both failure modes collapse to ``None`` (it
    never raises):

    * ``json.JSONDecodeError`` — the string is not valid JSON (malformed /
      truncated / non-JSON transport noise).
    * ``pydantic.ValidationError`` — the string is valid JSON but violates the
      model contract (missing required field, out-of-enum value, uncoercible
      type, ...).

    Returning ``None`` keeps the fallback decision with the **caller**: the
    detector caller (AI-HARD-1) should fall back to the heuristic instead of
    emitting a benign verdict, and the Tester caller (AI-HARD-2) should fall
    back to ``NEEDS_REVISION`` instead of fail-open ``APPROVED``.

    Args:
        raw: The raw LLM response string expected to contain JSON.
        model_cls: A Pydantic ``BaseModel`` subclass to validate against.

    Returns:
        A validated instance of ``model_cls`` on success, or ``None`` when the
        JSON is malformed or fails model validation.
    """
    try:
        data = json.loads(raw)
        return model_cls.model_validate(data)
    except json.JSONDecodeError:
        logger.debug("_parse_model_json: malformed JSON for %s", model_cls.__name__)
        return None
    except ValidationError:
        logger.debug(
            "_parse_model_json: JSON failed %s validation", model_cls.__name__
        )
        return None


__all__ = [
    "VerdictEnum",
    "ConfidenceEnum",
    "TesterVerdictEnum",
    "AIDetectionResult",
    "TesterVerdict",
    "_parse_model_json",
]
