"""Tutoring performance scoring — DATA-GAM-3.

A single **pure** function, :func:`compute_performance_score`, turns the persisted
turns of a socratic tutoring session into a gamification/progress score in
``[0, 100]``. It is deliberately I/O-free (no DB, no network, no clock, no
mutation of its input) so it is fully deterministic and unit-testable; the
persistence side (loading the turns, writing ``chat_sessions.performance_score``)
lives in ``routes_ai.complete_chat_session``.

Signal model (in priority order)
--------------------------------
Turns are the ``chat_messages`` rows persisted by TPP-4 — dicts with ``role``
(``"user"`` = student, ``"assistant"`` = tutor), ``content``, and an optional
``metadata`` dict. Per-turn evaluation is not yet written into ``metadata``
(it is ``None`` today), so the function reads it **defensively** and degrades:

1. **Evaluation signal (preferred, future-proof).** If any student turn carries a
   per-turn evaluation in ``metadata`` — a numeric ``score``/``performance``
   (``0..1`` or ``0..100``) or a boolean/labelled correctness
   (``is_correct`` / ``correct`` / ``verdict``) — the score is the mean of those
   normalised signals, scaled to ``[0, 100]``.
2. **Engagement fallback.** With no per-turn evaluation available, the score is
   derived from how much the student actually engaged: the number of substantive
   student turns (non-empty content) mapped against a target depth, lightly
   rewarded for sustained, non-trivial answers. This never fabricates mastery — a
   single throwaway turn scores low, a full multi-turn dialogue scores high.
3. **Insufficient signal → ``None``.** No turns at all, or no student turn with any
   real content, returns ``None`` (never a forced ``0``) so a session that can't be
   scored does not pollute dashboard averages with a false zero.

The result is always clamped to ``[0, 100]`` and returned as an ``int`` (or
``None``).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Engagement fallback: number of substantive student turns that maps to a full
# score. Mirrors the tutor's interaction cadence (a completed socratic dialogue is
# a handful of student turns), so a student who sees the dialogue through scores
# near the top even without per-turn grading.
_TARGET_STUDENT_TURNS = 4

# A student turn shorter than this (after stripping) is treated as trivial
# ("ok", "sim") — it still counts as engagement but is not rewarded as a
# substantive answer in the fallback.
_SUBSTANTIVE_MIN_CHARS = 12


def _clamp_100(value: float) -> int:
    """Clamp ``value`` into ``[0, 100]`` and return it as an int."""
    return int(round(max(0.0, min(100.0, value))))


def _is_student_turn(turn: Any) -> bool:
    return isinstance(turn, dict) and turn.get("role") == "user"


def _turn_content(turn: Dict[str, Any]) -> str:
    content = turn.get("content")
    return content.strip() if isinstance(content, str) else ""


def _normalise_score(raw: Any) -> Optional[float]:
    """Coerce a per-turn numeric score into a ``0..1`` fraction, or ``None``.

    Accepts a ``0..1`` fraction as-is and a ``1 < x <= 100`` value as a percentage.
    Non-numeric / out-of-range / boolean values return ``None`` (booleans are
    handled by :func:`_normalise_correctness`, not here).
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    val = float(raw)
    if 0.0 <= val <= 1.0:
        return val
    if 1.0 < val <= 100.0:
        return val / 100.0
    return None


def _normalise_correctness(meta: Dict[str, Any]) -> Optional[float]:
    """Coerce a boolean/labelled correctness signal into ``0.0``/``1.0``/``0.5``.

    Returns ``None`` when no recognised correctness key is present.
    """
    for key in ("is_correct", "correct"):
        val = meta.get(key)
        if isinstance(val, bool):
            return 1.0 if val else 0.0

    verdict = meta.get("verdict")
    if isinstance(verdict, str):
        v = verdict.strip().upper()
        if v in ("APPROVED", "CORRECT", "PASS", "PASSED"):
            return 1.0
        if v in ("REJECTED", "INCORRECT", "FAIL", "FAILED"):
            return 0.0
        if v in ("NEEDS_REVISION", "PARTIAL"):
            return 0.5
    return None


def _evaluation_fraction(turn: Dict[str, Any]) -> Optional[float]:
    """Extract a ``0..1`` evaluation fraction from a student turn's metadata.

    Prefers an explicit numeric score, then a correctness/verdict label. Returns
    ``None`` when the turn carries no per-turn evaluation signal.
    """
    meta = turn.get("metadata")
    if not isinstance(meta, dict):
        return None

    for key in ("score", "performance", "performance_score"):
        frac = _normalise_score(meta.get(key))
        if frac is not None:
            return frac

    return _normalise_correctness(meta)


def compute_performance_score(
    turns: Optional[Sequence[Dict[str, Any]]],
) -> Optional[int]:
    """Compute a ``[0, 100]`` performance score from a session's persisted turns.

    Pure: no I/O, no side effects, does not mutate ``turns``. Returns ``None`` when
    the signal is insufficient to score honestly (no turns, or no student turn with
    any real content). See the module docstring for the signal model.
    """
    if not turns:
        return None

    student_turns: List[Dict[str, Any]] = [t for t in turns if _is_student_turn(t)]
    if not student_turns:
        return None

    # A session is only scorable if the student actually said something.
    substantive = [t for t in student_turns if _turn_content(t)]
    if not substantive:
        return None

    # 1) Preferred: per-turn evaluation signal, if any student turn carries one.
    evaluations = [
        frac
        for frac in (_evaluation_fraction(t) for t in student_turns)
        if frac is not None
    ]
    if evaluations:
        mean = sum(evaluations) / len(evaluations)
        return _clamp_100(mean * 100.0)

    # 2) Fallback: engagement depth. Base credit for turning up and answering,
    # scaled by how far the dialogue was carried, with a small bonus for turns
    # that are substantive rather than one-word acknowledgements.
    depth = len(student_turns)
    depth_fraction = min(1.0, depth / _TARGET_STUDENT_TURNS)

    long_answers = sum(
        1 for t in substantive if len(_turn_content(t)) >= _SUBSTANTIVE_MIN_CHARS
    )
    substance_fraction = long_answers / depth  # relative to all student turns

    # 60% of the score comes from carrying the dialogue to depth, 40% from the
    # student's answers being substantive rather than throwaway.
    score = 100.0 * (0.6 * depth_fraction + 0.4 * substance_fraction)
    return _clamp_100(score)
