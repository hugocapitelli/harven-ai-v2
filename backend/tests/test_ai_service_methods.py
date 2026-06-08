"""ASYNC-AI-3 — coverage of the 5 public AIService methods in two modes.

Mode (a) **live-fake**: a ``FakeAsyncOpenAI`` is injected (``mock_mode=False``), so
each method exercises the real ``_call_openai`` async path — proving the migration
to ``AsyncOpenAI`` works end to end without touching the network.

Mode (b) **MOCK_MODE**: no OPENAI_API_KEY, so ``_call_openai`` raises ``MOCK_MODE``
and each method returns its canned fallback. Proves the mock path still works.

Both modes assert NO real network call: live-fake records calls on the injected
fake; MOCK_MODE constructs no client at all.

Methods covered: generate_questions, socratic_dialogue, detect_ai_content,
edit_response, validate_response.
"""
from __future__ import annotations

import json

from fakes import FakeAsyncOpenAI
from services.ai_service import AIService


# ---------------------------------------------------------------------------
# Canned JSON the fake returns for the JSON-mode methods (creator/analyst/tester).
# ---------------------------------------------------------------------------
QUESTIONS_JSON = json.dumps({
    "questions": [
        {"text": "Por que X implica Y?", "expected_depth": "analise",
         "intention": "reflect", "skill": "analyze", "followup_prompts": ["E se nao?"]},
    ]
})
ANALYST_JSON = json.dumps({
    "probability": 0.82, "confidence": "high", "verdict": "likely_ai",
    "indicators": [{"type": "ai_phrase", "description": "padrao", "weight": 0.1}],
})
TESTER_JSON = json.dumps({
    "verdict": "APPROVED", "score": 0.9,
    "criteria": {"pedagogical": {"pass": True, "score": 0.9}},
})


def _svc_with(response_text: str):
    """AIService with an injected async fake returning ``response_text``."""
    fake = FakeAsyncOpenAI(response_text=response_text)
    svc = AIService(client=fake, sync_client=None)
    return svc, fake


# ===========================================================================
# (a) live-fake mode — real _call_openai path, no network
# ===========================================================================

async def test_generate_questions_live_fake():
    svc, fake = _svc_with(QUESTIONS_JSON)
    out = await svc.generate_questions(chapter_content="conteudo", chapter_title="Cap 1")
    assert len(fake.calls) == 1                       # hit the (fake) client, not net
    assert isinstance(out["questions"], list) and len(out["questions"]) == 1
    assert out["questions"][0]["text"].startswith("Por que")
    assert "metadata" in out and "tokens_used" in out["metadata"]


async def test_socratic_dialogue_live_fake():
    svc, fake = _svc_with("Boa pergunta. O que voce acha que acontece a seguir? ")
    out = await svc.socratic_dialogue(
        student_message="nao sei",
        chapter_content="conteudo",
        initial_question={"text": "O que e X?"},
        interactions_remaining=3,
    )
    assert len(fake.calls) == 1
    assert out["response"]["content"].endswith("? ")
    assert out["response"]["has_question"] is True
    assert out["session_status"]["interactions_remaining"] == 2


async def test_detect_ai_content_live_fake():
    svc, fake = _svc_with(ANALYST_JSON)
    out = await svc.detect_ai_content(text="Diante do exposto, e importante ressaltar...")
    assert len(fake.calls) == 1
    assert out["ai_detection"]["verdict"] == "likely_ai"
    assert out["ai_detection"]["probability"] == 0.82


async def test_edit_response_live_fake():
    svc, fake = _svc_with("Texto editado, mais claro. Concorda? ")
    out = await svc.edit_response(orientador_response="texto bruto")
    assert len(fake.calls) == 1
    assert out["edited_text"] == "Texto editado, mais claro. Concorda? "
    assert out["ends_with_question"] is True


async def test_validate_response_live_fake():
    svc, fake = _svc_with(TESTER_JSON)
    out = await svc.validate_response(edited_response="resposta editada")
    assert len(fake.calls) == 1
    assert out["verdict"] == "APPROVED"
    assert out["score"] == 0.9


async def test_live_fake_makes_no_real_network_call():
    """Aggregate guard: across all 5 methods the only client touched is the fake."""
    fake = FakeAsyncOpenAI(response_text=QUESTIONS_JSON)
    svc = AIService(client=fake, sync_client=None)
    assert svc.mock_mode is False
    await svc.generate_questions(chapter_content="c", chapter_title="t")
    # The injected fake IS the client; a real AsyncOpenAI was never constructed.
    assert svc.client is fake
    assert len(fake.calls) == 1


# ===========================================================================
# (b) MOCK_MODE — canned fallbacks, no client constructed
# ===========================================================================

async def test_all_methods_mock_mode(mock_ai_service):
    """All 5 methods return valid shapes via canned fallbacks with no client."""
    svc: AIService = mock_ai_service
    assert svc.mock_mode is True and svc.client is None

    q = await svc.generate_questions(chapter_content="c", chapter_title="Cap")
    assert isinstance(q["questions"], list) and len(q["questions"]) >= 1
    assert q["metadata"]["model_used"] == "mock"

    d = await svc.socratic_dialogue(
        student_message="__INIT__",
        chapter_content="c",
        initial_question={"text": "Q"},
        interactions_remaining=3,
    )
    assert d["response"]["has_question"] is True
    assert d["analytics"]["model_used"] == "mock"

    a = await svc.detect_ai_content(text="acho que tipo sei la ne kkk")
    # No JSON-mode client -> heuristic fallback path.
    assert "ai_detection" in a and "verdict" in a["ai_detection"]

    e = await svc.edit_response(orientador_response="texto original?")
    assert e["model_used"] == "mock"
    assert e["edited_text"] == "texto original?"

    v = await svc.validate_response(edited_response="resposta")
    assert v["verdict"] == "APPROVED"
    assert set(v["criteria"]).issuperset(
        {"pedagogical", "structural", "clarity", "engagement", "originality", "inclusivity"}
    )
