"""Server-side points whitelist for gamification (EPIC-SEC / SEC-ADMIN-4).

Academic-integrity rule: the number of points awarded for an activity is decided
**by the server**, never by the client. ``ActivityCreate.points`` sent in a
request body is ignored; the gamification routes derive points from this map via
:func:`points_for`. An unknown ``activity_type`` yields the safe default ``0``
rather than honouring an attacker-supplied value, so a forged ``activity_type``
can never inflate the leaderboard.

This module is the **single source of truth** for activity points — both
``create_activity`` and ``complete_content`` reference it, eliminating the old
hardcoded ``"points": 10`` in ``complete_content``.
"""
from __future__ import annotations

# Canonical activity_type -> points map. Extend here (one place) when new
# gamified activities are introduced. Values are intentionally conservative.
ACTIVITY_POINTS: dict[str, int] = {
    "content_completed": 10,
    "course_completed": 100,
    "session_completed": 5,
    "achievement_unlocked": 20,
    "certificate_issued": 50,
}

# Points granted for an activity_type that is not in the whitelist. ``0`` is the
# fail-safe: an unknown / forged type contributes nothing to the leaderboard.
DEFAULT_POINTS: int = 0


def points_for(activity_type: str | None) -> int:
    """Return the server-defined points for ``activity_type``.

    The client never supplies the value: an unknown or ``None`` ``activity_type``
    resolves to :data:`DEFAULT_POINTS` (``0``), never to a body-controlled number.
    """
    if not activity_type:
        return DEFAULT_POINTS
    return ACTIVITY_POINTS.get(str(activity_type), DEFAULT_POINTS)
