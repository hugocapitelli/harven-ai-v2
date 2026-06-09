"""AI-HARD-4 — resilience of ``_call_openai`` against degenerate completions.

Two defects in the single inference path (``ai_service._call_openai`` and the
socratic caller) are covered here:

* **#55 — empty choices.** A content-filter / error envelope / OpenAI-compatible
  gateway can answer with ``choices=[]``. Reading ``response.choices[0]`` would
  raise a bare ``IndexError`` that escapes every public method's
  ``except AIServiceError`` and 500s the route. The fix normalizes it into an
  ``AIServiceError("empty completion")`` at the single inference point, so all 5
  consumers degrade through their existing handlers (fallback or honest raise),
  never an ``IndexError``.

* **#56 — empty content.** ``socratic_dialogue`` output goes straight into a chat
  bubble; an empty/whitespace-only model reply would render a blank tutor bubble.
  The fix retries the socratic pass EXACTLY ONCE (FinOps — no loop) and, if still
  empty, substitutes ``SOCRATIC_FALLBACK_CONTENT`` (a genuine, non-empty socratic
  question). The success return shape is unchanged.

The fake (``tests/fakes.py``) is extended for this story: ``FakeAsyncOpenAI`` now
accepts ``empty_choices=True`` (every completion carries ``choices=[]``) and a
``responses=[...]`` per-call script (each step a content string or the sentinel
``{"empty_choices": True}``) so a single test can drive empty-then-valid content
or empty-choices on a chosen call.
"""
from __future__ import annotations

import logging

import pytest

from fakes import FakeAsyncOpenAI
from services.ai_service import (
    AIService,
    AIServiceError,
    SOCRATIC_FALLBACK_CONTENT,
)


def _svc(**fake_kwargs):
    """AIService with an injected async fake (mock_mode forced off)."""
    fake = FakeAsyncOpenAI(**fake_kwargs)
    svc = AIService(client=fake, sync_client=None)
    return svc, fake


# ===========================================================================
# #55 — empty choices: _call_openai raises AIServiceError, NOT IndexError
# ===========================================================================

async def test_call_openai_empty_choices_raises_aiserviceerror_not_indexerror(caplog):
    """``choices=[]`` -> ``AIServiceError('empty completion')`` (never IndexError)."""
    svc, fake = _svc(empty_choices=True)
    with caplog.at_level(logging.WARNING, logger="services.ai_service"):
        with pytest.raises(AIServiceError) as exc:
            await svc._call_openai("sys", "user")
    assert "empty completion" in str(exc.value)
    assert len(fake.calls) == 1
    # The degrade is observable as a WARN (not silenced, not a stack trace).
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_call_openai_empty_choices_is_not_indexerror():
    """Regression oracle: the failure type is AIServiceError, not IndexError."""
    svc, _ = _svc(empty_choices=True)
    raised = None
    try:
        await svc._call_openai("sys", "user")
    except Exception as e:  # noqa: BLE001 - we assert on the concrete type
        raised = e
    assert isinstance(raised, AIServiceError)
    assert not isinstance(raised, IndexError)


# ===========================================================================
# #55 — each of the 5 public methods degrades on empty-choices WITHOUT a 500
# (no IndexError escapes; each falls into its existing fallback or honest raise)
# ===========================================================================

async def test_generate_questions_empty_choices_degrades_no_500():
    """generate_questions wraps _call_openai in try/except AIServiceError; an
    empty-choices completion surfaces as AIServiceError (not IndexError/500)."""
    svc, _ = _svc(empty_choices=True)
    with pytest.raises(AIServiceError) as exc:
        await svc.generate_questions(chapter_content="c", chapter_title="t")
    assert not isinstance(exc.value, IndexError)
    assert "empty completion" in str(exc.value) or "Falha" in str(exc.value)


async def test_socratic_dialogue_empty_choices_degrades_no_500():
    """socratic_dialogue's first pass hits empty-choices -> AIServiceError; the
    non-MOCK branch re-raises AIServiceError (route's except handles it), never
    an IndexError 500."""
    svc, _ = _svc(empty_choices=True)
    with pytest.raises(AIServiceError) as exc:
        await svc.socratic_dialogue(
            student_message="nao sei",
            chapter_content="c",
            initial_question={"text": "O que e X?"},
            interactions_remaining=3,
        )
    assert not isinstance(exc.value, IndexError)
    assert "empty completion" in str(exc.value)


async def test_detect_ai_content_empty_choices_falls_back_to_heuristic():
    """detect_ai_content swallows the inference failure (except Exception) and
    falls back HARD to the heuristic — no IndexError, no 500, valid shape."""
    svc, _ = _svc(empty_choices=True)
    text = "acho que tipo sei la ne kkk"
    out = await svc.detect_ai_content(text=text)
    # Heuristic path: probability matches the pure heuristic, shape intact.
    assert out["ai_detection"]["probability"] == svc._heuristic_ai_detection(text)["probability"]
    assert out["ai_detection"]["verdict"] in {"likely_human", "uncertain", "likely_ai"}


async def test_edit_response_empty_choices_degrades_no_500():
    """edit_response re-raises the non-MOCK AIServiceError (handled upstream),
    never an IndexError 500."""
    svc, _ = _svc(empty_choices=True)
    with pytest.raises(AIServiceError) as exc:
        await svc.edit_response(orientador_response="texto bruto")
    assert not isinstance(exc.value, IndexError)
    assert "empty completion" in str(exc.value)


async def test_validate_response_empty_choices_is_unknown_degraded_not_500():
    """validate_response catches the AIServiceError transport failure and fails
    CLOSED to UNKNOWN/degraded (never APPROVED, never an IndexError 500)."""
    svc, _ = _svc(empty_choices=True)
    out = await svc.validate_response(edited_response="resposta")
    assert out["verdict"] != "APPROVED"
    assert out["verdict"] in ("UNKNOWN", "NEEDS_REVISION")
    assert out["degraded"] is True


# ===========================================================================
# #56 — empty content: 1 retry, then deterministic non-empty socratic fallback
# ===========================================================================

async def test_socratic_empty_content_retries_once_and_uses_retry(caplog):
    """First model reply is whitespace-only; a single retry returns a valid
    reply -> the retry's content is used (exactly 2 chat calls)."""
    svc, fake = _svc(responses=["   ", "Boa reflexao. O que voce acha disso? "])
    with caplog.at_level(logging.WARNING, logger="services.ai_service"):
        out = await svc.socratic_dialogue(
            student_message="nao sei",
            chapter_content="c",
            initial_question={"text": "O que e X?"},
            interactions_remaining=3,
        )
    assert len(fake.calls) == 2  # exactly 1 retry (FinOps: max 1)
    assert out["response"]["content"] == "Boa reflexao. O que voce acha disso? "
    assert out["response"]["content"].strip() != ""
    # The retry path is observable as a WARN.
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_socratic_both_empty_uses_fallback_non_empty_with_question(caplog):
    """Both the first reply AND the single retry are empty -> the deterministic
    ``SOCRATIC_FALLBACK_CONTENT`` is returned: non-empty and carries a '?'."""
    svc, fake = _svc(responses=["", "   "])
    with caplog.at_level(logging.WARNING, logger="services.ai_service"):
        out = await svc.socratic_dialogue(
            student_message="nao sei",
            chapter_content="c",
            initial_question={"text": "O que e X?"},
            interactions_remaining=3,
        )
    assert len(fake.calls) == 2  # 1 original + 1 retry, no loop
    content = out["response"]["content"]
    assert content == SOCRATIC_FALLBACK_CONTENT
    assert content.strip() != ""
    assert "?" in content
    assert out["response"]["has_question"] is True  # derived from the '?'
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_socratic_fallback_constant_is_a_real_non_empty_question():
    """The fallback constant itself must never be a blank bubble."""
    assert SOCRATIC_FALLBACK_CONTENT.strip() != ""
    assert "?" in SOCRATIC_FALLBACK_CONTENT


async def test_socratic_never_returns_empty_content_across_paths():
    """socratic_dialogue never returns a whitespace-only ``content`` to the
    frontend, across: valid first reply, empty-then-valid, both-empty."""
    # (1) valid on first try
    svc1, _ = _svc(response_text="Pergunta direta? ")
    out1 = await svc1.socratic_dialogue(
        student_message="x", chapter_content="c",
        initial_question={"text": "Q"}, interactions_remaining=3,
    )
    assert out1["response"]["content"].strip() != ""
    # (2) empty then valid
    svc2, _ = _svc(responses=["  ", "Reflita mais? "])
    out2 = await svc2.socratic_dialogue(
        student_message="x", chapter_content="c",
        initial_question={"text": "Q"}, interactions_remaining=3,
    )
    assert out2["response"]["content"].strip() != ""
    # (3) both empty -> fallback
    svc3, _ = _svc(responses=["", ""])
    out3 = await svc3.socratic_dialogue(
        student_message="x", chapter_content="c",
        initial_question={"text": "Q"}, interactions_remaining=3,
    )
    assert out3["response"]["content"].strip() != ""


async def test_socratic_success_return_shape_unchanged():
    """The success contract is intact: response{content,has_question,
    is_final_interaction} + session_status + analytics — even via the fallback.

    AI-HARD-7 (#31) additively surfaces the empty-content fallback as a degraded
    state, so this path now ALSO carries top-level ``degraded``/``reason``. The
    pre-existing keys and their sub-structures remain unchanged (additive only),
    which is what this test guards.
    """
    svc, _ = _svc(responses=["", ""])  # forces the fallback path
    out = await svc.socratic_dialogue(
        student_message="x", chapter_content="c",
        initial_question={"text": "Q"}, interactions_remaining=3,
    )
    # Pre-existing top-level keys are still present and unchanged in shape.
    assert {"response", "session_status", "analytics"}.issubset(set(out))
    assert set(out["response"]) == {"content", "has_question", "is_final_interaction"}
    assert set(out["session_status"]) == {"interactions_remaining", "should_finalize"}
    assert "tokens_used" in out["analytics"]
    # AI-HARD-7: the fallback path is degraded, surfaced additively at top level.
    assert out["degraded"] is True
    assert out["reason"] == "empty_content_fallback"


async def test_socratic_happy_path_no_retry_single_call():
    """A non-empty first reply takes NO retry — exactly one chat call (FinOps)."""
    svc, fake = _svc(response_text="O que voce acha? ")
    out = await svc.socratic_dialogue(
        student_message="x", chapter_content="c",
        initial_question={"text": "Q"}, interactions_remaining=3,
    )
    assert len(fake.calls) == 1  # no retry on the happy path
    assert out["response"]["content"] == "O que voce acha? "
