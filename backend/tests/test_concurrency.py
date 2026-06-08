"""ASYNC-AI-3 — concurrency regression suite (bug #1: blocked event loop).

This is the *oracle* for the async fix. The pattern is fail-before / pass-after:

* **Pre-fix** (synchronous ``OpenAI`` inside ``async def _call_openai``): N awaited
  LLM calls serialize on the single event loop. Wall-clock ≈ N × delay. The
  concurrency assertion FAILS.
* **Post-fix** (``AsyncOpenAI`` awaited): the calls overlap under ``asyncio.gather``.
  Wall-clock ≈ delay (the slowest single call), NOT the sum. The assertion PASSES.

The fail-before behavior is proven directly (not just asserted in prose) by
``test_blocking_client_serializes_PROOF`` below, which constructs an ``AIService``
whose injected client BLOCKS the loop (``time.sleep`` in a non-awaiting ``create``)
— i.e. it reproduces the pre-fix defect and shows this exact assertion catches it.

Everything runs headless: no OPENAI_API_KEY, no network. ``asyncio_mode = auto``
(pyproject.toml) lets ``async def test_*`` run without per-test markers.

Run:  pytest backend/tests/ -q          (full suite)
      pytest backend/tests/test_concurrency.py -q
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from fakes import _FakeChatCompletion
from services.ai_service import AIService


# Generous timing margins keep this stable on slow/loaded CI (per Dev Notes:
# prefer a slack threshold over microsecond precision).
DELAY = 0.30          # simulated per-call LLM latency (seconds)
N_CALLS = 5           # concurrent callers
SLOW_MULT = 3.0       # post-fix budget: total must be well under N × delay
SERIAL_MULT = 0.9     # pre-fix proof: serialized total must exceed ~N × delay × this


def _socratic_kwargs():
    return dict(
        student_message="Por que isso funciona assim?",
        chapter_content="Conteudo de referencia para o dialogo socratico.",
        initial_question={"text": "O que voce entende por X?"},
        interactions_remaining=3,
    )


async def test_concurrent_socratic_dialogue_does_not_serialize(ai_service_factory):
    """POST-FIX: N slow concurrent socratic turns overlap (loop stays free).

    With the AsyncOpenAI fix, ``asyncio.gather`` of N calls — each sleeping DELAY —
    finishes in ≈ DELAY, NOT N × DELAY. If the event loop were blocked (pre-fix
    synchronous client), this would take ≈ N × DELAY and the assertion would FAIL.
    """
    svc, fake, _ = ai_service_factory(
        delay=DELAY, response_text="Boa reflexao. O que mais voce nota? "
    )

    t0 = time.perf_counter()
    results = await asyncio.gather(
        *[svc.socratic_dialogue(**_socratic_kwargs()) for _ in range(N_CALLS)]
    )
    total = time.perf_counter() - t0

    # All calls actually happened against the fake (no network).
    assert len(fake.calls) == N_CALLS
    assert len(results) == N_CALLS
    for r in results:
        assert "response" in r and "content" in r["response"]

    # The crux: concurrent, not serialized.
    assert total < DELAY * SLOW_MULT, (
        f"event loop appears blocked: {N_CALLS} calls x {DELAY}s took {total:.2f}s "
        f"(expected < {DELAY * SLOW_MULT:.2f}s if truly concurrent)"
    )
    # And it genuinely waited for the (single) slowest call — not a no-op.
    assert total >= DELAY * 0.8


async def test_health_check_not_starved_during_slow_dialogue(ai_service_factory):
    """POST-FIX: a fast 'health-check' coroutine returns promptly while a slow LLM
    dialogue is in flight on the same loop.

    Models the real symptom: ``/health`` must not wait behind a 5-30s tutor turn.
    The fast probe should complete in a small fraction of the slow call's duration.
    """
    svc, _, _ = ai_service_factory(delay=DELAY)

    health_latency = {}

    async def slow_dialogue():
        await svc.socratic_dialogue(**_socratic_kwargs())

    async def health_probe():
        # Let the slow call start first, then time how long a trivial await takes.
        await asyncio.sleep(0.01)
        h0 = time.perf_counter()
        await asyncio.sleep(0)  # a yield the loop must service promptly
        health_latency["ms"] = (time.perf_counter() - h0) * 1000

    await asyncio.gather(slow_dialogue(), health_probe())

    # If the loop were frozen by a blocking client, this yield would be delayed by
    # the full DELAY. Post-fix it returns in single-digit ms.
    assert health_latency["ms"] < (DELAY * 1000) * 0.5, (
        f"health probe was starved ({health_latency['ms']:.1f}ms) — event loop blocked"
    )


async def test_blocking_client_serializes_PROOF():
    """FAIL-BEFORE PROOF: reproduce the pre-fix defect and show this oracle catches it.

    We inject a client whose ``create`` is a coroutine that BLOCKS the loop with
    ``time.sleep`` (no ``await`` yield) — exactly how the old synchronous ``OpenAI``
    client behaved when called from ``async def``. Under ``asyncio.gather`` these
    cannot overlap, so wall-clock ≈ N × DELAY. We assert the *serialized* behavior,
    proving the concurrency thresholds above are meaningful (they would FAIL here).
    """

    class _BlockingCompletions:
        def __init__(self, parent):
            self._p = parent

        async def create(self, **kwargs):
            self._p.calls.append(kwargs)
            time.sleep(DELAY)  # blocks the entire event loop — the bug.
            return _FakeChatCompletion("blocked response ?")

    class _BlockingClient:
        def __init__(self):
            self.calls = []
            self.chat = SimpleNamespace(completions=_BlockingCompletions(self))

    blocking = _BlockingClient()
    svc = AIService(client=blocking, sync_client=None)

    t0 = time.perf_counter()
    await asyncio.gather(
        *[svc.socratic_dialogue(**_socratic_kwargs()) for _ in range(N_CALLS)]
    )
    total = time.perf_counter() - t0

    assert len(blocking.calls) == N_CALLS
    # Serialized: total is ~N × DELAY. This is the pre-fix world; the post-fix
    # assertions (total < DELAY * SLOW_MULT) would FAIL against this client — which
    # is precisely what makes them a regression oracle.
    assert total >= DELAY * N_CALLS * SERIAL_MULT, (
        f"blocking client did not serialize as expected: {total:.2f}s"
    )
    # Sanity: this serialized total is NOT within the concurrent budget.
    assert total > DELAY * SLOW_MULT
