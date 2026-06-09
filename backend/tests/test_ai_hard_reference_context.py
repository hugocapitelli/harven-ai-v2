"""AI-HARD-6 (bug #27) — socratic reference-context cap raised 4000 -> 15000 via
a named constant + centralized in the ``_select_reference_context`` retrieval seam.

Bug #27: ``socratic_dialogue`` embedded the chapter reference content via the
inline magic number ``chapter_content[:4000]``. For chapters longer than ~4000
chars the tutor lost factual grounding on the second half — inconsistent with
``generate_questions`` (which already uses ``[:15000]``). This story:

  * declares ``REFERENCE_CONTEXT_MAX_CHARS = 15000`` (module scope),
  * centralizes the slicing in ``AIService._select_reference_context``
    (a seam ready to evolve into relevance-aware retrieval on ``student_message``),
  * routes ``socratic_dialogue``'s context assembly through that seam.

These tests pin the new behavior end to end. The injected ``FakeAsyncOpenAI``
records every chat ``create`` kwargs in ``fake.calls``; the system message
(``messages[0]["content"]``) carries ``SOCRATES_PROMPT`` + the static context,
i.e. the reference content actually sent to the model. We assert on it directly.

Markers ("BEGIN5000", "AT8000", "END14000", "PAST15000") are embedded at known
offsets so we can prove which slice of the chapter reached the model — no
reliance on char-counting fragile substrings.
"""
from __future__ import annotations

from fakes import FakeAsyncOpenAI
from services.ai_service import REFERENCE_CONTEXT_MAX_CHARS, AIService


SOCRATIC_REPLY = "Boa reflexao. O que mais voce nota nesse trecho? "


def _svc():
    """AIService with an injected async fake returning a fixed socratic reply."""
    fake = FakeAsyncOpenAI(response_text=SOCRATIC_REPLY)
    return AIService(client=fake, sync_client=fake), fake


def _system_message(fake: FakeAsyncOpenAI) -> str:
    """The system message of the (single) chat call — SOCRATES_PROMPT + context."""
    assert len(fake.calls) == 1
    messages = fake.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    return messages[0]["content"]


def _chapter_with_markers(total_len: int) -> str:
    """A chapter of ``total_len`` chars with sentinel markers at fixed offsets.

    Markers land at 0 (BEGIN5000 region), ~5000, ~8000, ~14000 and ~15200 so a
    test can assert which offsets survived the slice. Filler is the digit-cycle
    so the string is deterministic and exactly ``total_len`` long.
    """
    base = ("0123456789" * ((total_len // 10) + 1))[:total_len]
    chars = list(base)

    def _stamp(offset: int, marker: str) -> None:
        if offset + len(marker) <= total_len:
            chars[offset:offset + len(marker)] = list(marker)

    _stamp(0, "BEGIN0000")
    _stamp(5000, "AT5000")
    _stamp(8000, "AT8000")
    _stamp(14000, "AT14000")
    _stamp(15200, "PAST15000")  # only present when total_len is large enough
    return "".join(chars)


# ---------------------------------------------------------------------------
# Constant + seam unit-level contract
# ---------------------------------------------------------------------------

def test_reference_cap_constant_is_15000():
    """The named cap is 15000 — aligned with generate_questions' ``[:15000]``."""
    assert REFERENCE_CONTEXT_MAX_CHARS == 15000


def test_select_reference_context_truncates_at_cap():
    """The seam returns the head capped at REFERENCE_CONTEXT_MAX_CHARS for long input."""
    svc = AIService.__new__(AIService)  # seam is pure; no init/network needed
    long_chapter = "x" * 30000
    out = svc._select_reference_context(long_chapter)
    assert len(out) == REFERENCE_CONTEXT_MAX_CHARS
    assert out == long_chapter[:REFERENCE_CONTEXT_MAX_CHARS]


def test_select_reference_context_short_chapter_is_integral():
    """A chapter at/below the cap is returned whole — no truncation, no padding."""
    svc = AIService.__new__(AIService)
    short_chapter = "conteudo curto do capitulo"
    out = svc._select_reference_context(short_chapter)
    assert out == short_chapter
    assert len(out) == len(short_chapter)


def test_select_reference_context_accepts_student_message_kwarg():
    """The seam accepts ``student_message`` (retrieval extension point) and, today,
    returns the same head slice regardless of its value — no behavioral coupling yet."""
    svc = AIService.__new__(AIService)
    chapter = "y" * 20000
    without = svc._select_reference_context(chapter)
    with_msg = svc._select_reference_context(chapter, student_message="o que e isso?")
    assert without == with_msg == chapter[:REFERENCE_CONTEXT_MAX_CHARS]
    assert len(with_msg) == REFERENCE_CONTEXT_MAX_CHARS


def test_select_reference_context_at_exact_cap_is_integral():
    """A chapter exactly at the cap is returned whole (boundary: <= limit)."""
    svc = AIService.__new__(AIService)
    chapter = "z" * REFERENCE_CONTEXT_MAX_CHARS
    out = svc._select_reference_context(chapter)
    assert out == chapter
    assert len(out) == REFERENCE_CONTEXT_MAX_CHARS


# ---------------------------------------------------------------------------
# End-to-end: socratic_dialogue routes the reference slice through the seam
# ---------------------------------------------------------------------------

async def test_socratic_chapter_between_4000_and_15000_keeps_content_past_4000():
    """A chapter between 4000 and 15000 chars: content past the OLD 4000 cap now
    reaches the model (regression-proof for the raised cap)."""
    svc, fake = _svc()
    chapter = _chapter_with_markers(12000)  # 4000 < 12000 < 15000
    await svc.socratic_dialogue(
        student_message="nao sei",
        chapter_content=chapter,
        initial_question={"text": "O que e X?"},
        interactions_remaining=3,
    )
    system_msg = _system_message(fake)
    # The whole chapter (<= cap) is present, including offsets well past 4000.
    assert "AT5000" in system_msg
    assert "AT8000" in system_msg
    assert chapter[4000:12000] in system_msg     # the entire post-4000 tail shipped
    assert chapter in system_msg                  # integral (no truncation under cap)


async def test_socratic_chapter_over_15000_is_cut_at_cap():
    """A chapter longer than 15000 is truncated to exactly the cap: content up to
    15000 ships, content past 15000 does not."""
    svc, fake = _svc()
    chapter = _chapter_with_markers(20000)  # > 15000
    await svc.socratic_dialogue(
        student_message="continua",
        chapter_content=chapter,
        initial_question={"text": "O que e X?"},
        interactions_remaining=3,
    )
    system_msg = _system_message(fake)
    # Up-to-cap content (incl. the 14000 marker) is present...
    assert "AT14000" in system_msg
    assert chapter[:REFERENCE_CONTEXT_MAX_CHARS] in system_msg
    # ...but the marker stamped past the cap is dropped (unambiguous proof that
    # content beyond char 15000 did not reach the model). The digit-cycle filler
    # repeats, so only the unique marker can certify the truncation boundary.
    assert "PAST15000" not in system_msg
    # The exact slice the seam returns is the head capped at the constant.
    assert svc._select_reference_context(chapter) == chapter[:REFERENCE_CONTEXT_MAX_CHARS]


async def test_socratic_short_chapter_is_integral_no_regression():
    """A short chapter (<= cap) is embedded whole — no truncation regression."""
    svc, fake = _svc()
    chapter = "Capitulo curto: a fotossintese converte luz em energia quimica."
    await svc.socratic_dialogue(
        student_message="por que?",
        chapter_content=chapter,
        initial_question={"text": "O que e fotossintese?"},
        interactions_remaining=3,
    )
    system_msg = _system_message(fake)
    assert chapter in system_msg


async def test_socratic_no_4000_truncation_remains():
    """Guard against the old magic number: a chapter just over 4000 is NOT cut at
    4000 — the slice that previously vanished now appears in the model prompt."""
    svc, fake = _svc()
    chapter = _chapter_with_markers(6000)  # just over the old 4000 cap
    await svc.socratic_dialogue(
        student_message="hmm",
        chapter_content=chapter,
        initial_question={"text": "O que e X?"},
        interactions_remaining=3,
    )
    system_msg = _system_message(fake)
    # The 4000..6000 slice that the legacy ``[:4000]`` would have dropped is present.
    assert chapter[4000:6000] in system_msg
    assert "AT5000" in system_msg
