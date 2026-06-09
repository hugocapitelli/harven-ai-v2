"""AI-HARD-7 (#31) — surface the degraded/mock state instead of impersonating a
working tutor.

When the API key is absent/placeholder at startup the service runs in mock mode:
``socratic_dialogue`` serves canned, chapter-agnostic prompts and ``edit_response``
returns the orientador text UNEDITED. Before this story the only signal was
``analytics.model_used == "mock"`` — buried in analytics and never surfaced to the
caller as a top-level flag, and no WARN was emitted, so a misconfigured deploy
silently served filler that looked like a real socratic tutor.

This story promotes that implicit signal to an EXPLICIT top-level contract and adds
observability:

* ``socratic_dialogue`` in mock mode -> ``degraded: True`` + ``reason:
  "mock_mode_no_api_key"`` at the top level (re-injected into its re-mounted return),
  plus a WARN at serve time.
* The empty-content socratic fallback (AI-HARD-4) -> the SAME contract with ``reason:
  "empty_content_fallback"``.
* ``edit_response`` in mock mode -> ``mock: True`` + ``degraded: True`` + ``reason:
  "mock_mode_no_api_key"`` at the top level, ``edited_text`` unchanged (now flagged
  as not-actually-edited), plus a WARN.

The change is **purely additive**: no existing field (``response.content``,
``session_status``, ``analytics``, ``edited_text``) is removed/renamed/retyped. The
SUCCESS path (real reply from a valid key) NEVER injects ``degraded``/``mock`` and
NEVER emits a degradation WARN.
"""
from __future__ import annotations

import logging

import pytest

from fakes import FakeAsyncOpenAI
from services.ai_service import AIService, SOCRATIC_FALLBACK_CONTENT


# ---------------------------------------------------------------------------
# Service builders — mirror the established patterns in the sibling suites.
# ---------------------------------------------------------------------------
def _live_svc(**fake_kwargs):
    """AIService with an injected async fake — ``mock_mode`` forced OFF (real
    reply path). Used for the success / live-fake assertions."""
    fake = FakeAsyncOpenAI(**fake_kwargs)
    svc = AIService(client=fake, sync_client=None)
    assert svc.mock_mode is False
    return svc, fake


@pytest.fixture
def mock_svc(monkeypatch):
    """An ``AIService`` forced into MOCK_MODE (no API key) — canned-fallback path.

    Same construction as the shared ``mock_ai_service`` fixture, inlined here so this
    suite is self-contained and the assertions read top-to-bottom.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")

    import config

    config.get_settings.cache_clear()

    from services.ai_service import AIService as _AIService

    svc = _AIService()
    assert svc.mock_mode is True
    assert svc.client is None
    return svc


# ===========================================================================
# socratic_dialogue — MOCK MODE: degraded contract + WARN
# ===========================================================================
async def test_socratic_mock_mode_surfaces_degraded_and_reason(mock_svc):
    """Mock-mode ``socratic_dialogue`` carries top-level ``degraded is True`` +
    ``reason == 'mock_mode_no_api_key'`` — promoted from the buried
    ``analytics.model_used == 'mock'`` signal."""
    out = await mock_svc.socratic_dialogue(
        student_message="Quero explorar: o que e X?",
        chapter_content="conteudo do capitulo",
        initial_question={"text": "O que e X?"},
        interactions_remaining=3,
    )
    assert out["degraded"] is True
    assert out["reason"] == "mock_mode_no_api_key"


async def test_socratic_mock_mode_existing_fields_intact(mock_svc):
    """Additive change: ``response.content``/``session_status``/``analytics`` keep
    their shape; the buried ``model_used == 'mock'`` signal is preserved."""
    out = await mock_svc.socratic_dialogue(
        student_message="Quero explorar: o que e X?",
        chapter_content="conteudo do capitulo",
        initial_question={"text": "O que e X?"},
        interactions_remaining=3,
    )
    # response block intact and non-empty (still a real chat bubble payload).
    assert isinstance(out["response"]["content"], str)
    assert out["response"]["content"].strip() != ""
    assert "has_question" in out["response"]
    assert "is_final_interaction" in out["response"]
    # session_status block intact.
    assert "interactions_remaining" in out["session_status"]
    assert "should_finalize" in out["session_status"]
    # analytics block intact — the legacy implicit signal still present.
    assert out["analytics"]["model_used"] == "mock"
    assert "tokens_used" in out["analytics"]


async def test_socratic_mock_mode_emits_warn(mock_svc, caplog):
    """Serving a mock socratic reply emits a WARN identifying method + reason."""
    with caplog.at_level(logging.WARNING, logger="services.ai_service"):
        await mock_svc.socratic_dialogue(
            student_message="nao sei",
            chapter_content="c",
            initial_question={"text": "Q"},
            interactions_remaining=3,
        )
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warns, "expected a WARN when serving a degraded mock reply"
    blob = " ".join(r.getMessage() for r in warns)
    assert "socratic_dialogue" in blob
    assert "mock_mode_no_api_key" in blob


# ===========================================================================
# socratic_dialogue — EMPTY-CONTENT FALLBACK (aligned to AI-HARD-4)
# ===========================================================================
async def test_socratic_empty_content_fallback_is_degraded(caplog):
    """Both the first reply AND the single retry are empty -> the deterministic
    socratic fallback is served, carrying the SAME degraded contract with
    ``reason == 'empty_content_fallback'``."""
    svc, fake = _live_svc(responses=["", "   "])
    with caplog.at_level(logging.WARNING, logger="services.ai_service"):
        out = await svc.socratic_dialogue(
            student_message="nao sei",
            chapter_content="c",
            initial_question={"text": "Q"},
            interactions_remaining=3,
        )
    # AI-HARD-4 behavior preserved: fallback content is served (1 original + 1 retry).
    assert out["response"]["content"] == SOCRATIC_FALLBACK_CONTENT
    assert len(fake.calls) == 2
    # AI-HARD-7: the served fallback is explicitly degraded.
    assert out["degraded"] is True
    assert out["reason"] == "empty_content_fallback"
    # And the degradation is observable as a WARN naming method + reason.
    blob = " ".join(
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    )
    assert "socratic_dialogue" in blob
    assert "empty_content_fallback" in blob


# ===========================================================================
# edit_response — MOCK MODE: mock + degraded contract + WARN
# ===========================================================================
async def test_edit_response_mock_mode_surfaces_mock_and_degraded(mock_svc):
    """Mock-mode ``edit_response`` carries top-level ``mock is True`` +
    ``degraded is True`` + ``reason``, and ``edited_text`` is the orientador text
    UNCHANGED (now flagged as not-actually-edited)."""
    orientador = "Texto do orientador, inalterado?"
    out = await mock_svc.edit_response(orientador_response=orientador)
    assert out["mock"] is True
    assert out["degraded"] is True
    assert out["reason"] == "mock_mode_no_api_key"
    # The pre-existing contract is untouched: text is returned verbatim.
    assert out["edited_text"] == orientador
    assert out["model_used"] == "mock"


async def test_edit_response_mock_mode_emits_warn(mock_svc, caplog):
    """Serving a mock edit emits a WARN identifying method + reason."""
    with caplog.at_level(logging.WARNING, logger="services.ai_service"):
        await mock_svc.edit_response(orientador_response="texto bruto")
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warns, "expected a WARN when serving a degraded mock edit"
    blob = " ".join(r.getMessage() for r in warns)
    assert "edit_response" in blob
    assert "mock_mode_no_api_key" in blob


# ===========================================================================
# SUCCESS PATH (live-fake, mock OFF) — NO degraded/mock flags, NO degradation WARN
# ===========================================================================
async def test_socratic_success_path_no_degraded_no_warn(caplog):
    """A real (live-fake) socratic reply NEVER injects ``degraded``/``mock`` and
    emits NO degradation WARN."""
    svc, _ = _live_svc(
        responses=["Boa pergunta. O que voce acha que acontece a seguir? "]
    )
    with caplog.at_level(logging.WARNING, logger="services.ai_service"):
        out = await svc.socratic_dialogue(
            student_message="acho que sim",
            chapter_content="c",
            initial_question={"text": "Q"},
            interactions_remaining=3,
        )
    # degraded/mock are absent (or falsey) on the success path.
    assert out.get("degraded") is not True
    assert out.get("mock") is not True
    # analytics reflects a real model, not the mock sentinel.
    assert out["analytics"]["model_used"] != "mock"
    # No degradation WARN was emitted.
    degraded_warns = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "DEGRADED" in r.getMessage()
    ]
    assert not degraded_warns


async def test_edit_response_success_path_no_degraded_no_warn(caplog):
    """A real (live-fake) edit NEVER injects ``degraded``/``mock`` and emits NO
    degradation WARN; ``edited_text`` is the model output, not the input."""
    svc, _ = _live_svc(responses=["Texto editado, mais claro. Concorda? "])
    with caplog.at_level(logging.WARNING, logger="services.ai_service"):
        out = await svc.edit_response(orientador_response="texto bruto")
    assert out.get("degraded") is not True
    assert out.get("mock") is not True
    assert out["model_used"] != "mock"
    assert out["edited_text"] == "Texto editado, mais claro. Concorda? "
    degraded_warns = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "DEGRADED" in r.getMessage()
    ]
    assert not degraded_warns
