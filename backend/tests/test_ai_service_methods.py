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
import logging

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

    # AI-HARD-5: the ``__INIT__`` sentinel is gone; the frontend sends the real
    # opening text. A normal opening message exercises the same mock path.
    d = await svc.socratic_dialogue(
        student_message="Quero explorar a seguinte questao: o que e X?",
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


# ===========================================================================
# AI-HARD-1 — detector contract hardening (bug #30): the LLM JSON is routed
# through ``AIDetectionResult`` (coerce/clamp/enum) and falls back HARD to the
# heuristic on any contract failure. No path may 500; no spurious flag.
# ===========================================================================

def _detect_json(**fields) -> str:
    """Build a raw analyst JSON string from arbitrary fields."""
    return json.dumps(fields)


async def test_detect_probability_string_is_coerced_no_500():
    """probability as the string '0.8' is coerced to float, no TypeError/500."""
    svc, _ = _svc_with(_detect_json(probability="0.8", confidence="high", verdict="likely_ai"))
    out = await svc.detect_ai_content(text="Diante do exposto, pode-se afirmar que.")
    assert out["ai_detection"]["probability"] == 0.8        # coerced + round(2)
    assert out["ai_detection"]["verdict"] == "likely_ai"
    assert out["ai_detection"]["flag"] == "alta_probabilidade_texto_IA"  # 0.8 > 0.70


async def test_detect_probability_null_falls_back_to_heuristic_not_03():
    """probability: null -> contract fails -> hard heuristic fallback (NOT 0.3)."""
    svc, _ = _svc_with(_detect_json(probability=None, confidence="medium", verdict="uncertain"))
    text = "acho que tipo sei la ne"  # human markers -> heuristic well below 0.3
    out = await svc.detect_ai_content(text=text)
    heuristic = svc._heuristic_ai_detection(text)
    assert out["ai_detection"]["probability"] == heuristic["probability"]
    assert out["ai_detection"]["probability"] != 0.3        # benign default is gone
    assert out["ai_detection"]["flag"] is None


async def test_detect_probability_absent_key_falls_back_to_heuristic():
    """probability key missing entirely -> hard heuristic fallback (#29)."""
    svc, _ = _svc_with(_detect_json(confidence="medium", verdict="uncertain"))
    text = "acho que tipo sei la ne kkk"
    out = await svc.detect_ai_content(text=text)
    assert out["ai_detection"]["probability"] == svc._heuristic_ai_detection(text)["probability"]
    assert out["ai_detection"]["probability"] != 0.3


async def test_detect_probability_above_range_is_clamped_no_spurious_flag():
    """probability 1.5 -> clamped to 1.0 (valid), no TypeError; round/compare safe."""
    svc, _ = _svc_with(_detect_json(probability=1.5, confidence="high", verdict="likely_ai"))
    out = await svc.detect_ai_content(text="texto qualquer aqui para analise.")
    assert out["ai_detection"]["probability"] == 1.0        # clamped to [0,1]


async def test_detect_probability_below_range_is_clamped_no_flag():
    """probability -0.2 -> clamped to 0.0; no spurious flag, no crash."""
    svc, _ = _svc_with(_detect_json(probability=-0.2, confidence="low", verdict="likely_human"))
    out = await svc.detect_ai_content(text="texto qualquer aqui para analise.")
    assert out["ai_detection"]["probability"] == 0.0        # clamped to [0,1]
    assert out["ai_detection"]["flag"] is None              # 0.0 never > 0.70


async def test_detect_verdict_out_of_enum_falls_back_to_heuristic():
    """verdict not in {likely_human,uncertain,likely_ai} -> contract fails -> heuristic.
    The arbitrary verdict never leaks verbatim into the response."""
    svc, _ = _svc_with(_detect_json(probability=0.9, confidence="high", verdict="DEFINITELY_AI"))
    out = await svc.detect_ai_content(text="acho que tipo sei la ne")
    assert out["ai_detection"]["verdict"] in {"likely_human", "uncertain", "likely_ai"}
    assert out["ai_detection"]["verdict"] != "DEFINITELY_AI"


async def test_detect_confidence_out_of_enum_falls_back_to_heuristic():
    """confidence not in {low,medium,high} -> contract fails -> heuristic; never verbatim."""
    svc, _ = _svc_with(_detect_json(probability=0.9, confidence="extreme", verdict="likely_ai"))
    out = await svc.detect_ai_content(text="acho que tipo sei la ne")
    assert out["ai_detection"]["confidence"] in {"low", "medium", "high"}


async def test_detect_happy_path_unchanged():
    """Valid float prob + enum verdict/confidence -> observable behavior unchanged."""
    svc, fake = _svc_with(_detect_json(
        probability=0.82, confidence="high", verdict="likely_ai",
        indicators=[{"type": "ai_phrase", "description": "x", "weight": 0.1}],
    ))
    out = await svc.detect_ai_content(text="Diante do exposto, pode-se afirmar que.")
    assert len(fake.calls) == 1
    assert out["ai_detection"]["verdict"] == "likely_ai"
    assert out["ai_detection"]["probability"] == 0.82
    assert out["ai_detection"]["flag"] == "alta_probabilidade_texto_IA"
    assert out["ai_detection"]["indicators"] == [
        {"type": "ai_phrase", "description": "x", "weight": 0.1}
    ]


async def test_detect_route_response_model_is_stable_superset():
    """The route's declared response_model validates BOTH return paths intact."""
    from schemas.ai import AIDetectionResponse

    # LLM path
    svc, _ = _svc_with(_detect_json(probability=0.82, confidence="high", verdict="likely_ai"))
    out_llm = await svc.detect_ai_content(text="Diante do exposto, pode-se afirmar que.")
    model_llm = AIDetectionResponse.model_validate(out_llm)
    # No declared field is dropped on re-serialization.
    assert model_llm.ai_detection.probability == 0.82
    assert model_llm.metrics.text.message_length_words > 0
    assert set(model_llm.model_dump()).issuperset(
        {"analysis_id", "timestamp", "ai_detection", "metrics", "flags",
         "observations", "recommendation"}
    )

    # Heuristic/fallback path
    svc2, _ = _svc_with(_detect_json(confidence="medium", verdict="uncertain"))  # no probability
    out_heur = await svc2.detect_ai_content(text="acho que tipo sei la ne")
    AIDetectionResponse.model_validate(out_heur)


# ===========================================================================
# AI-HARD-3 — heuristic quality: neutral PT-BR connectors removed + density
# weighting with a cap. Legit essays stay below 0.70; cliché-dense scores higher.
# ===========================================================================

async def test_neutral_ptbr_connectors_removed_from_ai_phrases():
    """The 8 neutral connectors are gone; genuine AI markers remain."""
    from services.ai_service import AI_PHRASES

    removed = {
        "nesse sentido", "em suma", "nesse contexto", "em linhas gerais",
        "em termos gerais", "por conseguinte", "dessa forma", "sendo assim",
    }
    assert removed.isdisjoint(AI_PHRASES)
    # genuine indicators preserved
    assert "diante do exposto" in AI_PHRASES
    assert "pode-se afirmar que" in AI_PHRASES


async def test_ptbr_essay_with_neutral_connectors_not_flagged():
    """An essay full of neutral connectors stays < 0.70 and is NOT flagged.

    Goes through the heuristic (mock/fallback) — the removed connectors no longer
    contribute, so 5-6 of them cannot trip the flag."""
    svc, _ = _svc_with(_detect_json(confidence="medium", verdict="uncertain"))  # no prob -> heuristic
    essay = (
        "A reforma agraria e um tema complexo. Dessa forma, precisamos analisar o contexto. "
        "Nesse sentido, o pequeno produtor enfrenta desafios. Em suma, a politica publica importa. "
        "Nesse contexto, o credito rural e essencial. Por conseguinte, a renda no campo melhora. "
        "Sendo assim, conclui-se que o investimento traz retorno social ao longo do tempo. "
        "Em linhas gerais, o cooperativismo fortalece a agricultura familiar de forma sustentavel."
    )
    out = await svc.detect_ai_content(text=essay)
    assert out["ai_detection"]["probability"] < 0.70
    assert out["ai_detection"]["flag"] is None
    assert "alta_probabilidade_texto_IA" not in out["flags"]
    assert out["recommendation"] != "Revisao manual recomendada"


async def test_cliche_dense_scores_higher_than_human_same_size():
    """A short cliché-dense text scores strictly higher than a same-size human text."""
    svc = AIService.__new__(AIService)  # heuristic is pure; no init/network needed

    dense = "Diante do exposto, pode-se afirmar que vale ressaltar que cabe mencionar."
    human_same = "Ontem fui na feira e comprei tomate barato porque estava na promocao hoje cedo."
    d = svc._heuristic_ai_detection(dense)
    h = svc._heuristic_ai_detection(human_same)
    assert d["probability"] > h["probability"]


async def test_ai_phrase_contribution_is_capped_below_flag():
    """Presence-only AI matches cannot, alone, push a legit essay over the flag.

    A long essay where the surviving AI-phrases appear stays < 0.70 because the
    aggregate AI-phrase contribution is capped (density-weighted)."""
    svc = AIService.__new__(AIService)
    essay = (
        "A educacao transforma realidades. " * 30
        + "Diante do exposto, pode-se afirmar que a escola importa. "
        + "Vale ressaltar que o professor e central. Cabe mencionar o papel da familia. "
        + "E importante ressaltar o investimento. E fundamental destacar a continuidade. "
        + "E valido salientar o acesso universal."
    )
    out = svc._heuristic_ai_detection(essay)
    assert out["probability"] < 0.70  # cap keeps presence-only matches below the flag


async def test_density_short_dense_beats_long_sparse_same_matches():
    """Same AI-phrase count: a short (dense) text scores higher than a long (sparse) one."""
    svc = AIService.__new__(AIService)
    short_dense = "Diante do exposto, pode-se afirmar que vale ressaltar isso."
    long_sparse = ("texto neutro aqui " * 60) + "Diante do exposto, pode-se afirmar que vale ressaltar isso."
    s = svc._heuristic_ai_detection(short_dense)
    long_ = svc._heuristic_ai_detection(long_sparse)
    assert s["probability"] > long_["probability"]


# ===========================================================================
# AI-HARD-2 — Tester (quality gate) no longer fails open to a fabricated
# APPROVED (bug #32). The LLM JSON is routed through ``TesterVerdict``; parse
# and transport failures fail CLOSED (NEEDS_REVISION/UNKNOWN) with a degraded
# flag and an ERROR log. APPROVED only surfaces from a well-formed payload that
# actually carries that verdict. MOCK_MODE tags its stub with ``mock: true``.
# ===========================================================================

async def test_validate_malformed_json_is_needs_revision_not_approved(caplog):
    """Unparseable Tester JSON -> NEEDS_REVISION (never the old fabricated APPROVED)."""
    svc, fake = _svc_with("this is not json at all {")
    with caplog.at_level(logging.ERROR, logger="services.ai_service"):
        out = await svc.validate_response(edited_response="resposta editada")
    assert len(fake.calls) == 1
    assert out["verdict"] == "NEEDS_REVISION"
    assert out["verdict"] != "APPROVED"
    assert out["degraded"] is True
    assert "score" in out and out["score"] is None
    # The degrade is observable: an ERROR record was emitted (not silenced/warning).
    assert any(r.levelno == logging.ERROR for r in caplog.records)


async def test_validate_transport_error_is_unknown_degraded_with_error_log(caplog):
    """A raised client exception (transport) -> UNKNOWN + degraded + ERROR log; never APPROVED."""
    fake = FakeAsyncOpenAI(
        response_text=TESTER_JSON,
        raise_exc=RuntimeError("tester upstream down"),
    )
    svc = AIService(client=fake, sync_client=None)
    with caplog.at_level(logging.ERROR, logger="services.ai_service"):
        out = await svc.validate_response(edited_response="anything")
    assert out["verdict"] in ("UNKNOWN", "NEEDS_REVISION")
    assert out["verdict"] != "APPROVED"
    assert out["degraded"] is True
    assert out.get("reason") == "transport_error"
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records, "transport failure must log at ERROR level"
    # The root cause is surfaced in the ERROR log (not swallowed).
    assert any("tester upstream down" in r.getMessage() for r in error_records)


async def test_validate_well_formed_payload_returns_approved():
    """A well-formed payload that carries APPROVED -> APPROVED (only valid path to it)."""
    svc, fake = _svc_with(TESTER_JSON)
    out = await svc.validate_response(edited_response="resposta editada")
    assert len(fake.calls) == 1
    assert out["verdict"] == "APPROVED"
    assert out["score"] == 0.9
    assert out.get("degraded") is not True   # success is never flagged degraded
    assert "mock" not in out                  # a real verdict is not tagged mock


async def test_validate_mock_mode_tags_verdict_with_mock_true(mock_ai_service):
    """MOCK_MODE stub verdict is tagged ``mock: true`` so consumers can tell it apart."""
    svc: AIService = mock_ai_service
    assert svc.mock_mode is True and svc.client is None
    out = await svc.validate_response(edited_response="resposta")
    assert out["verdict"] == "APPROVED"
    assert out["mock"] is True
    assert set(out["criteria"]).issuperset(
        {"pedagogical", "structural", "clarity", "engagement", "originality", "inclusivity"}
    )


async def test_validate_valid_json_without_verdict_is_needs_revision_not_approved(caplog):
    """Syntactically valid JSON that LACKS 'verdict' fails the contract -> NEEDS_REVISION.

    The contract violation collapses to ``None`` in ``_parse_model_json``; it must
    never fail open to APPROVED just because the JSON parsed."""
    svc, fake = _svc_with(json.dumps({"score": 0.95, "criteria": {"clarity": {"pass": True}}}))
    with caplog.at_level(logging.ERROR, logger="services.ai_service"):
        out = await svc.validate_response(edited_response="resposta editada")
    assert len(fake.calls) == 1
    assert out["verdict"] == "NEEDS_REVISION"
    assert out["verdict"] != "APPROVED"
    assert out["degraded"] is True
    assert any(r.levelno == logging.ERROR for r in caplog.records)


async def test_validate_no_except_path_returns_approved():
    """Exhaustive guard: across mock / malformed / no-verdict / transport, only the
    well-formed APPROVED payload yields APPROVED — no failure path fabricates it."""
    # (1) malformed JSON
    svc1, _ = _svc_with("not json {{")
    assert (await svc1.validate_response(edited_response="x"))["verdict"] != "APPROVED"
    # (2) valid JSON, no verdict
    svc2, _ = _svc_with(json.dumps({"score": 0.99}))
    assert (await svc2.validate_response(edited_response="x"))["verdict"] != "APPROVED"
    # (3) valid JSON, out-of-enum verdict
    svc3, _ = _svc_with(json.dumps({"verdict": "DEFINITELY_GREAT", "score": 0.99}))
    assert (await svc3.validate_response(edited_response="x"))["verdict"] != "APPROVED"
    # (4) transport exception
    fake = FakeAsyncOpenAI(response_text=TESTER_JSON, raise_exc=RuntimeError("down"))
    svc4 = AIService(client=fake, sync_client=None)
    assert (await svc4.validate_response(edited_response="x"))["verdict"] != "APPROVED"
