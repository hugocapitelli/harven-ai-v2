"""POD-1 — dedicated podcast branch + sentence-aware, lossless ``chunk_text``.

Covers the two defects fixed by this story (bug sweep #8 and #33):

* #8: ``audio_type='podcast'`` must roteirize the FULL (HTML-stripped) chapter
  body via a dedicated conversational prompt, never the summary/explanation
  short-form path. ``AIService.generate_podcast_script`` is the new seam.
* #33: ``chunk_text`` must FATIATE (never truncate) — every chunk is
  ``<= max_chars``, cuts fall on sentence boundaries, and the ordered
  concatenation of all chunks reproduces the input exactly (lossless
  round-trip). No silent ``text[:5000]`` cap remains reachable from this
  module.

``summary``/``explanation`` audio generation lives in ``routes_ai.py`` and is
NOT touched here (out of this story's scope) — this suite only proves the new
``services/ai_service.py`` seams (``strip_html``, ``chunk_text``,
``generate_podcast_script``) behave per the AC, so ``routes_ai.py`` can wire
the podcast branch to them.
"""
from __future__ import annotations

import string

from fakes import FakeAsyncOpenAI, FakeSyncOpenAI
from services.ai_service import (
    DEFAULT_CHUNK_MAX_CHARS,
    PODCAST_MIN_WORDS,
    AIService,
    chunk_text,
    strip_html,
)


def _svc_with_sync(fake_sync: FakeSyncOpenAI) -> AIService:
    """AIService with a real (injected) sync_client for the TTS-thread path.

    Mirrors ``AIService(client=..., sync_client=...)`` as used by
    ``tests/test_tts_job.py`` — the injection branch in ``AIService.__init__``
    only takes effect when ``client`` is ALSO provided (otherwise it falls
    through to constructing a REAL ``OpenAI``/``AsyncOpenAI`` from whatever
    ``OPENAI_API_KEY`` happens to be in the environment/.env — never what a
    headless unit test wants). The async client is an unused placeholder;
    ``generate_podcast_script`` only ever calls ``sync_client``.
    """
    return AIService(client=FakeAsyncOpenAI(), sync_client=fake_sync)


# ===========================================================================
# strip_html
# ===========================================================================

def test_strip_html_removes_tags_and_decodes_entities():
    html = "<p>Ola &amp; bem-vindo</p><p>Segunda linha &lt;aqui&gt;</p>"
    out = strip_html(html)
    assert "<p>" not in out and "</p>" not in out
    assert "&amp;" not in out and "&lt;" not in out
    assert "Ola & bem-vindo" in out
    assert "Segunda linha <aqui>" in out


def test_strip_html_preserves_paragraph_boundaries():
    """Block tags must not glue two paragraphs into a single run-on sentence —
    otherwise sentence-aware chunking downstream would see one giant unit."""
    html = "<p>Primeira frase.</p><p>Segunda frase.</p>"
    out = strip_html(html)
    # The two sentences must NOT be joined without any separating whitespace.
    assert "frase.Segunda" not in out
    assert "Primeira frase." in out
    assert "Segunda frase." in out


def test_strip_html_normalizes_whitespace():
    html = "<p>Texto   com   espacos</p>\n\n\n\n<p>e quebras excessivas</p>"
    out = strip_html(html)
    assert "   " not in out          # collapsed horizontal whitespace
    assert "\n\n\n" not in out       # collapsed 3+ blank lines


def test_strip_html_empty_input_returns_empty_string():
    assert strip_html("") == ""
    assert strip_html(None) == ""  # type: ignore[arg-type]


# ===========================================================================
# chunk_text — lossless, sentence-aware fatiation (bug #33)
# ===========================================================================

def test_chunk_text_short_input_is_a_single_chunk():
    text = "Um paragrafo curto que cabe facilmente em um unico chunk."
    chunks = chunk_text(text)
    assert chunks == [text]


def test_chunk_text_empty_input_returns_empty_list():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunk_text_long_input_produces_multiple_chunks_within_limit():
    # Build a long text from many short sentences so natural boundaries exist.
    sentence = "Esta e uma frase de exemplo sobre o tema estudado. "
    text = sentence * 400  # well over 5000 chars
    max_chars = 1000

    chunks = chunk_text(text, max_chars=max_chars)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= max_chars, f"chunk exceeds max_chars: {len(c)}"


def test_chunk_text_is_lossless_round_trip():
    """The AC's core contract: join(chunks) == original text, exactly."""
    sentence = "Capitulo sobre valuation e fluxo de caixa descontado. "
    text = (sentence * 300) + "Ultima frase sem padding final."
    chunks = chunk_text(text, max_chars=777)  # odd size to stress boundaries

    assert "".join(chunks) == text
    assert sum(len(c) for c in chunks) == len(text)


def test_chunk_text_default_max_chars_stays_under_elevenlabs_cap():
    """DEFAULT_CHUNK_MAX_CHARS must leave margin under the ElevenLabs 5000 cap."""
    assert DEFAULT_CHUNK_MAX_CHARS < 5000

    text = "Frase padrao para o teste de limite. " * 500
    chunks = chunk_text(text)  # uses the module default
    for c in chunks:
        assert len(c) <= 5000


def test_chunk_text_never_splits_mid_sentence_when_avoidable():
    """Boundaries should land on '. ' (or similar) whenever a natural break
    exists within the budget — verified by checking each non-final chunk
    ends at a sentence terminator (or is itself a hard-split fallback,
    excluded by construction here since sentences are short)."""
    sentence = "O aluno deve entender o conceito central antes de avancar. "
    text = sentence * 200
    chunks = chunk_text(text, max_chars=500)

    for c in chunks[:-1]:
        stripped = c.rstrip()
        assert stripped.endswith((".", "!", "?")), (
            f"chunk did not end on a sentence boundary: {stripped[-40:]!r}"
        )


def test_chunk_text_hard_split_fallback_for_oversized_single_sentence():
    """A single 'sentence' (no terminal punctuation) longer than max_chars must
    still be split losslessly — the documented fallback path."""
    huge_word_run = " ".join(
        "".join(string.ascii_lowercase) for _ in range(400)
    )  # no '.', '!' or '?' anywhere -> one giant "sentence"
    assert len(huge_word_run) > 2000

    chunks = chunk_text(huge_word_run, max_chars=300)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 300
    assert "".join(chunks) == huge_word_run


def test_chunk_text_covers_full_text_no_dropped_content_over_tts_limit():
    """AC: for any input >5000 chars, N>1 chunks cover 100% of the text — no
    code path truncates and discards the remainder."""
    text = "Bloco de conteudo pedagogico repetido para simular um capitulo longo. " * 200
    assert len(text) > 5000

    chunks = chunk_text(text, max_chars=5000)

    assert len(chunks) > 1
    assert all(len(c) <= 5000 for c in chunks)
    assert "".join(chunks) == text


# ===========================================================================
# generate_podcast_script — dedicated branch, full body, conversational (bug #8)
# ===========================================================================

def _long_chapter_html(paragraphs: int = 30) -> str:
    return "".join(
        f"<p>Paragrafo {i} sobre o tema do capitulo, com conteudo relevante "
        f"para o aluno entender o assunto em profundidade.</p>"
        for i in range(paragraphs)
    )


def test_generate_podcast_script_uses_sync_client_with_dedicated_prompt():
    fake_sync = FakeSyncOpenAI(response_text="Roteiro conversacional completo do capitulo.")
    svc = _svc_with_sync(fake_sync)

    script = svc.generate_podcast_script(_long_chapter_html(5), chapter_title="Cap 1")

    assert len(fake_sync.calls) == 1
    call = fake_sync.calls[0]
    # The system prompt sent must be the dedicated podcast prompt, not the
    # summary/explanation prompts.
    system_msg = call["messages"][0]["content"]
    assert "PodcastOS" in system_msg
    assert "roteiro" in system_msg.lower() or "Roteirista" in system_msg
    assert script == "Roteiro conversacional completo do capitulo."


def test_generate_podcast_script_sends_full_body_not_a_summary():
    """The user message passed to the LLM must contain the FULL html-stripped
    body — not a truncated head, not the summary/explanation short form."""
    fake_sync = FakeSyncOpenAI(response_text="Roteiro.")
    svc = _svc_with_sync(fake_sync)

    html = _long_chapter_html(40)
    plain = strip_html(html)
    svc.generate_podcast_script(html, chapter_title="Cap Longo")

    user_msg = fake_sync.calls[0]["messages"][1]["content"]
    # Every paragraph's distinguishing marker must survive into the prompt.
    assert "Paragrafo 0 " in user_msg
    assert "Paragrafo 39 " in user_msg
    assert "<p>" not in user_msg  # HTML was stripped before roteirization
    assert len(plain) > 0


def test_generate_podcast_script_mock_mode_falls_back_to_stripped_body():
    """No sync_client configured -> return the HTML-stripped body itself
    (never raise, never silently produce an empty/short clip).

    Constructed via injection (``client=FakeAsyncOpenAI()``) so ``__init__``
    never reaches out for a REAL ``OPENAI_API_KEY`` from the environment/.env,
    then ``sync_client`` is cleared to reproduce the "no sync client
    available" branch ``generate_podcast_script`` guards against.
    """
    svc = AIService(client=FakeAsyncOpenAI(), sync_client=None)
    assert svc.sync_client is None

    html = "<p>Conteudo minimo do capitulo.</p>"
    script = svc.generate_podcast_script(html)

    assert script == strip_html(html)
    assert "<p>" not in script


def test_generate_podcast_script_llm_failure_falls_back_gracefully():
    """If the LLM call raises, the job must still get narratable text (the
    stripped body) instead of propagating an exception into the TTS thread."""
    class _BoomCompletions:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class _BoomClient:
        def __init__(self):
            from types import SimpleNamespace
            self.chat = SimpleNamespace(completions=_BoomCompletions())

    svc = AIService(client=FakeAsyncOpenAI(), sync_client=_BoomClient())
    html = "<p>Conteudo que deve sobreviver ao erro do LLM.</p>"

    script = svc.generate_podcast_script(html)

    assert "Conteudo que deve sobreviver ao erro do LLM." in script


def test_generate_podcast_script_empty_body_returns_empty_string():
    fake_sync = FakeSyncOpenAI(response_text="Nao deveria ser chamado.")
    svc = _svc_with_sync(fake_sync)

    assert svc.generate_podcast_script("") == ""
    assert svc.generate_podcast_script("   ") == ""
    assert len(fake_sync.calls) == 0  # no LLM call for empty source


def test_generate_podcast_script_very_long_chapter_summarizes_sections_first():
    """Above PODCAST_SECTION_SUMMARY_THRESHOLD_CHARS, the body is summarized
    section-by-section (multiple LLM calls) before the final roteirization
    call — proving no silent head-truncation of a very long chapter."""
    fake_sync = FakeSyncOpenAI(response_text="Resumo ou roteiro (fake).")
    svc = _svc_with_sync(fake_sync)

    # 60 paragraphs of ~90 chars each -> comfortably over the 12000-char
    # section-summary threshold.
    html = _long_chapter_html(paragraphs=200)
    plain_len = len(strip_html(html))
    assert plain_len > 12000

    svc.generate_podcast_script(html, chapter_title="Cap Extenso")

    # At least one section-summary call PLUS the final roteirization call.
    assert len(fake_sync.calls) >= 2
    final_call = fake_sync.calls[-1]
    assert "PodcastOS" in final_call["messages"][0]["content"]


def test_generate_podcast_script_min_words_constant_matches_ac():
    """Sanity check that the AC's ~10min / >=1200 words target is wired into
    the prompt instruction, not silently drifted."""
    fake_sync = FakeSyncOpenAI(response_text="Roteiro.")
    svc = _svc_with_sync(fake_sync)

    svc.generate_podcast_script(_long_chapter_html(5))

    user_msg = fake_sync.calls[0]["messages"][1]["content"]
    assert str(PODCAST_MIN_WORDS) in user_msg
