"""Regression tests for the AI output contracts (story AI-HARD-0).

Fully offline — no network, no ``_call_openai``, no real LLM. Each test maps to
an Acceptance Criterion and documents the failure mode it guards against
(bugs #29, #30, #32 from the bug sweep). These are the falha-antes / passa-depois
cases that AI-HARD-1/2 rely on.

``backend/`` is on ``sys.path`` via the shared ``tests/conftest.py``, so the
``services.*`` imports resolve as top-level packages.
"""
import json

import pytest
from pydantic import ValidationError

from services.ai_contracts import (
    AIDetectionResult,
    TesterVerdict,
    _parse_model_json,
)


# ---------------------------------------------------------------------------
# AC1 — AIDetectionResult coerces a numeric-string probability to float.
# Guards bug #30: '0.8' > 0.70 would TypeError at the verbatim call-site.
# ---------------------------------------------------------------------------
def test_probability_string_coerced_to_float():
    result = AIDetectionResult(
        probability="0.8", verdict="likely_ai", confidence="high"
    )
    assert isinstance(result.probability, float)
    assert result.probability == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# AC2 — AIDetectionResult clamps probability to [0.0, 1.0].
# Guards bug #30: an out-of-range number flags the student or returns nonsense.
# ---------------------------------------------------------------------------
def test_probability_above_one_clamped_to_one():
    result = AIDetectionResult(
        probability=1.5, verdict="likely_ai", confidence="high"
    )
    assert result.probability == 1.0


def test_probability_negative_clamped_to_zero():
    result = AIDetectionResult(
        probability=-0.2, verdict="likely_human", confidence="low"
    )
    assert result.probability == 0.0


def test_probability_string_out_of_range_coerced_then_clamped():
    # Combined path: '1.5' (str) -> 1.5 (float) -> 1.0 (clamped).
    result = AIDetectionResult(
        probability="1.5", verdict="uncertain", confidence="medium"
    )
    assert result.probability == 1.0


def test_probability_within_range_unchanged():
    result = AIDetectionResult(
        probability=0.42, verdict="uncertain", confidence="medium"
    )
    assert result.probability == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# AC3 — AIDetectionResult validates verdict / confidence enums.
# Guards bug #30: verdict/confidence not restricted to the prompt enum.
# ---------------------------------------------------------------------------
def test_invalid_verdict_raises_validation_error():
    with pytest.raises(ValidationError):
        AIDetectionResult(
            probability=0.5, verdict="definitely_ai", confidence="high"
        )


def test_invalid_confidence_raises_validation_error():
    with pytest.raises(ValidationError):
        AIDetectionResult(
            probability=0.5, verdict="likely_ai", confidence="very_high"
        )


@pytest.mark.parametrize("verdict", ["likely_human", "uncertain", "likely_ai"])
def test_all_valid_verdicts_accepted(verdict):
    result = AIDetectionResult(
        probability=0.5, verdict=verdict, confidence="medium"
    )
    assert result.verdict.value == verdict


@pytest.mark.parametrize("confidence", ["low", "medium", "high"])
def test_all_valid_confidences_accepted(confidence):
    result = AIDetectionResult(
        probability=0.5, verdict="uncertain", confidence=confidence
    )
    assert result.confidence.value == confidence


# ---------------------------------------------------------------------------
# AC4 — TesterVerdict validates the verdict enum + clamps score.
# Guards bug #32: fail-open APPROVED + unbounded score.
# ---------------------------------------------------------------------------
def test_tester_invalid_verdict_raises_validation_error():
    with pytest.raises(ValidationError):
        TesterVerdict(verdict="MAYBE", score=0.8)


@pytest.mark.parametrize("verdict", ["APPROVED", "NEEDS_REVISION", "REJECTED"])
def test_tester_all_valid_verdicts_accepted(verdict):
    result = TesterVerdict(verdict=verdict, score=0.8)
    assert result.verdict.value == verdict


def test_tester_score_string_coerced_to_float():
    result = TesterVerdict(verdict="APPROVED", score="0.9")
    assert isinstance(result.score, float)
    assert result.score == pytest.approx(0.9)


def test_tester_score_above_one_clamped():
    result = TesterVerdict(verdict="APPROVED", score=1.5)
    assert result.score == 1.0


def test_tester_score_negative_clamped():
    result = TesterVerdict(verdict="REJECTED", score=-0.3)
    assert result.score == 0.0


def test_tester_score_optional_absent_is_none():
    result = TesterVerdict(verdict="NEEDS_REVISION")
    assert result.score is None


def test_tester_ignores_extra_llm_fields():
    # The LLM emits a rich `criteria` block; it must not break validation.
    result = TesterVerdict(
        verdict="APPROVED",
        score=0.8,
        criteria={"pedagogical": {"pass": True, "score": 0.9}},
    )
    assert result.verdict.value == "APPROVED"
    assert not hasattr(result, "criteria")


# ---------------------------------------------------------------------------
# AC5 — _parse_model_json: malformed -> None, good -> instance,
# valid-JSON-but-invalid-model -> None.
# ---------------------------------------------------------------------------
def test_parse_malformed_json_returns_none():
    assert _parse_model_json("{not valid json", AIDetectionResult) is None


def test_parse_empty_string_returns_none():
    assert _parse_model_json("", AIDetectionResult) is None


def test_parse_good_detector_json_returns_instance():
    raw = json.dumps(
        {"probability": 0.8, "verdict": "likely_ai", "confidence": "high"}
    )
    result = _parse_model_json(raw, AIDetectionResult)
    assert isinstance(result, AIDetectionResult)
    assert result.probability == pytest.approx(0.8)
    assert result.verdict.value == "likely_ai"


def test_parse_good_detector_json_with_string_probability_coerces():
    raw = json.dumps(
        {"probability": "1.5", "verdict": "uncertain", "confidence": "medium"}
    )
    result = _parse_model_json(raw, AIDetectionResult)
    assert isinstance(result, AIDetectionResult)
    assert result.probability == 1.0  # coerced then clamped


def test_parse_valid_json_failing_validation_returns_none():
    # Valid JSON, but verdict is out-of-enum -> ValidationError collapses to None.
    raw = json.dumps(
        {"probability": 0.5, "verdict": "definitely_ai", "confidence": "high"}
    )
    assert _parse_model_json(raw, AIDetectionResult) is None


def test_parse_valid_json_missing_required_field_returns_none():
    # Valid JSON, but `confidence` is missing -> ValidationError -> None.
    raw = json.dumps({"probability": 0.5, "verdict": "likely_ai"})
    assert _parse_model_json(raw, AIDetectionResult) is None


def test_parse_good_tester_json_returns_instance():
    raw = json.dumps({"verdict": "APPROVED", "score": 0.8})
    result = _parse_model_json(raw, TesterVerdict)
    assert isinstance(result, TesterVerdict)
    assert result.verdict.value == "APPROVED"
    assert result.score == pytest.approx(0.8)


def test_parse_tester_invalid_verdict_json_returns_none():
    raw = json.dumps({"verdict": "MAYBE", "score": 0.8})
    assert _parse_model_json(raw, TesterVerdict) is None
