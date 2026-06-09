"""AI-HARD-5 (#28/#57) — socratic prompt/context fidelity oracle.

Fail-before / pass-after guards for the prompt-assembly refactor of
``socratic_dialogue``:

  * The static context block (SOCRATES_PROMPT + question + reference content) is
    injected EXACTLY ONCE — in the ``system`` message — never re-wrapped into the
    per-turn ``user`` message.
  * The student's current turn ships RAW as ``{"role": "user", "content": <msg>}``
    — no ``CONTEXTO:\n...\n\nMENSAGEM DO ALUNO:\n...`` wrapper.
  * The replayed ``conversation_history`` is trimmed to the last
    ``MAX_HISTORY_TURNS`` turns; a transcript longer than K sends at most K turns.
  * Input message count / token budget per turn is bounded by K (does NOT grow
    with the full transcript across follow-ups).
  * The ``__INIT__`` sentinel is gone from ``backend/`` (grep == 0 active hits).

Headless: an injected ``FakeAsyncOpenAI`` records every ``create`` call's kwargs
(including the assembled ``messages``), so we inspect exactly what the model would
have received — no network, no DB.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fakes import FakeAsyncOpenAI
from services.ai_service import (
    AIService,
    MAX_HISTORY_TURNS,
    SOCRATES_PROMPT,
)


# A short, recognizable marker from the static context so we can count how many
# messages carry the preamble.
_CONTEXT_MARKER = "Pergunta em discussao:"
_REFERENCE_MARKER = "Conteudo de referencia:"
_OLD_WRAPPER_MARKERS = ("CONTEXTO:", "MENSAGEM DO ALUNO:")


def _svc(response_text: str = "Boa reflexao. O que mais voce nota? "):
    fake = FakeAsyncOpenAI(response_text=response_text)
    return AIService(client=fake, sync_client=None), fake


def _messages_of(call: dict) -> list:
    return call["messages"]


def _system_messages(messages: list) -> list:
    return [m for m in messages if m["role"] == "system"]


def _user_messages(messages: list) -> list:
    return [m for m in messages if m["role"] == "user"]


# ===========================================================================
# Context lives ONCE in the system message (not re-wrapped per turn)
# ===========================================================================
async def test_static_context_appears_once_in_system_not_in_user():
    svc, fake = _svc()
    await svc.socratic_dialogue(
        student_message="minha resposta crua",
        chapter_content="conteudo de referencia do capitulo",
        initial_question={"text": "O que e X?", "expected_answer": "uma definicao"},
        interactions_remaining=10,
    )
    assert len(fake.calls) == 1
    messages = _messages_of(fake.calls[0])

    systems = _system_messages(messages)
    assert len(systems) == 1, "exactly one system message expected"
    sys_content = systems[0]["content"]
    # The SOCRATES_PROMPT and the static context both live in the single system
    # message — injected once.
    assert SOCRATES_PROMPT in sys_content
    assert _CONTEXT_MARKER in sys_content
    assert _REFERENCE_MARKER in sys_content

    # The context block appears in EXACTLY ONE message across the whole payload.
    carrying_context = [m for m in messages if _CONTEXT_MARKER in m["content"]]
    assert len(carrying_context) == 1, "context preamble must appear exactly 1x"
    assert carrying_context[0]["role"] == "system"


async def test_student_turn_is_raw_user_without_wrapper():
    svc, fake = _svc()
    raw = "Acho que a resposta tem a ver com escala de producao"
    await svc.socratic_dialogue(
        student_message=raw,
        chapter_content="conteudo",
        initial_question={"text": "O que e X?"},
        interactions_remaining=10,
    )
    messages = _messages_of(fake.calls[0])
    last_user = _user_messages(messages)[-1]
    # The student message ships verbatim — no CONTEXTO:/MENSAGEM DO ALUNO: framing.
    assert last_user["content"] == raw
    for marker in _OLD_WRAPPER_MARKERS:
        assert marker not in last_user["content"]
    # And no message anywhere carries the old double-wrapper framing.
    for m in messages:
        for marker in _OLD_WRAPPER_MARKERS:
            assert marker not in m["content"], f"stale wrapper {marker!r} leaked"


# ===========================================================================
# History trim: last K turns only
# ===========================================================================
async def test_history_longer_than_k_is_trimmed_to_k():
    svc, fake = _svc()
    # Build a transcript with MANY more than K turns.
    n_turns = MAX_HISTORY_TURNS * 3
    history = []
    for i in range(n_turns):
        role = "user" if i % 2 == 0 else "assistant"
        history.append({"role": role, "content": f"turn-{i}"})

    await svc.socratic_dialogue(
        student_message="mensagem atual",
        chapter_content="conteudo",
        initial_question={"text": "Q?"},
        conversation_history=history,
        interactions_remaining=10,
    )
    messages = _messages_of(fake.calls[0])
    # Replayed history = messages minus the 1 system and the 1 current user turn.
    replayed = messages[1:-1]
    assert len(replayed) == MAX_HISTORY_TURNS, (
        f"history must be trimmed to {MAX_HISTORY_TURNS}, got {len(replayed)}"
    )
    # It is the TAIL (most recent K) that survives, not the head.
    expected_tail = history[-MAX_HISTORY_TURNS:]
    assert replayed == expected_tail


async def test_history_shorter_than_k_is_sent_whole():
    svc, fake = _svc()
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b?"},
        {"role": "user", "content": "c"},
    ]
    await svc.socratic_dialogue(
        student_message="d",
        chapter_content="conteudo",
        initial_question={"text": "Q?"},
        conversation_history=history,
        interactions_remaining=10,
    )
    messages = _messages_of(fake.calls[0])
    replayed = messages[1:-1]
    assert replayed == history  # nothing dropped when under the cap


# ===========================================================================
# Per-turn input is bounded by K (does not grow with the full transcript)
# ===========================================================================
async def test_messages_per_turn_bounded_by_k_across_followups():
    """Simulate 3+ follow-ups with an ever-growing transcript; each LLM call sends
    at most ``system + K history + 1 user`` messages — bounded, not N×."""
    svc, fake = _svc()
    upper_bound = MAX_HISTORY_TURNS + 2  # system + K + current user

    transcript: list = []
    for turn in range(5):  # 5 follow-ups, transcript grows each time
        msg = f"resposta do aluno no turno {turn}"
        await svc.socratic_dialogue(
            student_message=msg,
            chapter_content="conteudo",
            initial_question={"text": "Q?"},
            conversation_history=list(transcript),
            interactions_remaining=15,
        )
        # The just-issued call's payload size must respect the K bound regardless
        # of how long the transcript has grown.
        messages = _messages_of(fake.calls[-1])
        assert len(messages) <= upper_bound, (
            f"turn {turn}: {len(messages)} messages exceeds bound {upper_bound}"
        )
        # Context preamble still appears exactly once on every turn.
        carrying = [m for m in messages if _CONTEXT_MARKER in m["content"]]
        assert len(carrying) == 1 and carrying[0]["role"] == "system"

        # Grow the transcript as a real client would (user + assistant per turn).
        transcript.append({"role": "user", "content": msg})
        transcript.append({"role": "assistant", "content": "ok?"})

    assert len(fake.calls) == 5
    # The largest payload across all turns is still bounded by K (no linear blow-up
    # with the transcript length).
    assert max(len(_messages_of(c)) for c in fake.calls) <= upper_bound


# ===========================================================================
# Dead __INIT__ branch is gone from the backend source
# ===========================================================================
def test_no_active_init_sentinel_in_backend():
    """grep for ``__INIT__`` over backend/ returns 0 ACTIVE code occurrences.

    Only doc/comment mentions explaining the *removal* are tolerated (the source
    code path that compared ``student_message == "__INIT__"`` is gone)."""
    backend_dir = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        # -I skips binary files (stale ``.pyc`` caches); --include limits the scan
        # to Python source; --exclude-dir skips compiled bytecode caches.
        ["grep", "-rnI", "--include=*.py", "--exclude-dir=__pycache__",
         "__INIT__", str(backend_dir)],
        capture_output=True,
        text=True,
    )
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    offending = []
    for ln in lines:
        # path:lineno:content — keep only the code portion after the 2nd ':'.
        parts = ln.split(":", 2)
        code = parts[2] if len(parts) == 3 else ln
        stripped = code.strip()
        # Tolerate comment/doc mentions that merely DOCUMENT the removal.
        is_comment = stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'")
        # A removal-explaining comment references AI-HARD-5 / "removed" / "sentinel".
        documents_removal = any(
            token in stripped for token in ("AI-HARD-5", "removed", "sentinel", "removeu")
        )
        if is_comment and documents_removal:
            continue
        # This test file itself references the literal — exclude it.
        if parts[0].endswith("test_ai_hard_prompt_fidelity.py"):
            continue
        offending.append(ln)
    assert not offending, f"active __INIT__ usage still present:\n" + "\n".join(offending)
