"""In-scope authorization registry for the EPIC-SEC Fase 2 IDOR regression guard.

WHY THIS FILE EXISTS
====================
The application layer is the **only** authorization barrier in Harven.AI: there
is no RLS in the schema and the shared Supabase client decodes to ``service_role``
(it bypasses RLS by construction). Four IDORs (#49 avatar, #16 notifications,
#14 gamification, #25 session-review) plus the canonical chat-sessions IDOR (#2)
all share the same defect signature: a handler declares ``get_current_user`` only
as *proof of a valid JWT* — frequently bound to a parameter named ``_user`` to
signal "unused" — and then **never compares the authenticated identity to the
owner of the resource**, never role-gates, and trusts ``body.user_id``.

This registry is the **single source of truth** for which handlers are in scope
and how each one is authorized. The signature guard (``test_idor_signature_guard``)
cross-checks the live FastAPI app against this registry: every in-scope route MUST
be classified, and the live wiring MUST match its classification. Anything that is
in scope but unclassified — or whose live gate no longer matches — FAILS the build.

This is the "guard" that turns the pointwise SEC-ADMIN-2..5 / SEC-CHAT-* fixes
into a CI invariant.

HOW TO ADD A NEW HANDLER TO THE SCOPE
=====================================
When you add an authz-sensitive endpoint (anything that reads/mutates a resource
owned by a specific user, or that exposes privileged config), add ONE entry to
``IN_SCOPE`` below choosing the classification that matches how you protect it:

* ``ROLE_GATED``     — protected purely by ``Depends(require_role(...))`` in the
                       signature (no per-row owner check needed; the role IS the
                       authorization). The guard verifies the live route really
                       carries a ``require_role`` dependency.
* ``OWNER_CHECKED``  — protected by a per-row owner comparison INSIDE the handler
                       body (``assert_owner_or_role`` / ``require_self_or_role`` /
                       a ``load_session_or_404`` + owner assert). The guard verifies
                       the handler source calls one of the sanctioned authz helpers
                       (it cannot prove the semantics statically, so the behavioural
                       happy-path suite — ``test_idor_callers_happy_path`` — closes
                       that gap).
* ``ALLOWLISTED``    — a deliberate, documented exception that needs neither a role
                       gate nor an owner check (e.g. the STUDENT tutor carve-out, a
                       public/catalog read). MUST carry a ``reason``. Nothing is
                       skipped silently — an exception only counts if it is listed
                       here with a justification.

If a route is authz-sensitive and you do NOT add it here, the signature guard's
"unclassified in-scope endpoint" assertion will fail — which is the point:
new endpoints join the guard by default.

WHEN TO USE THE ALLOWLIST
=========================
Only for routes that genuinely must not compare an owner: the Socratic tutor
(``/api/ai/socrates/dialogue`` — must stay reachable by STUDENT, see SEC-SCOPE-3),
or read-only catalog endpoints with no per-user ownership. Never use it to silence
a real IDOR.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Classification vocabulary
# ---------------------------------------------------------------------------
ROLE_GATED = "ROLE_GATED"          # Depends(require_role(...)) in the signature
OWNER_CHECKED = "OWNER_CHECKED"    # per-row owner check in the handler body
ALLOWLISTED = "ALLOWLISTED"        # documented exception (needs a reason)

VALID_KINDS = frozenset({ROLE_GATED, OWNER_CHECKED, ALLOWLISTED})

# The sanctioned authorization helpers from the shared module. An OWNER_CHECKED
# handler MUST reference at least one of these in its source — ownership logic is
# never redefined inline (it lives in ``authz.py``, consumed by every story).
AUTHZ_HELPERS = frozenset(
    {
        "assert_owner_or_role",
        "require_self_or_role",
        "load_session_or_404",
        "assert_teacher_owns_discipline",
    }
)


@dataclass(frozen=True)
class ScopeEntry:
    """One authz-sensitive route under guard.

    Attributes:
        method: HTTP method (upper-case), e.g. ``"POST"``.
        path: the FastAPI route path template, e.g. ``"/chat-sessions/{session_id}"``.
        handler: the endpoint function name (used in failure messages).
        module: the source module the handler lives in (``routes_ai`` / ``routes_admin``
            / ``main``), so failures cite ``module:handler``.
        kind: one of :data:`ROLE_GATED` / :data:`OWNER_CHECKED` / :data:`ALLOWLISTED`.
        bug_ref: the originating bug-sweep id(s), for traceability.
        reason: required for :data:`ALLOWLISTED`; a one-line justification.
    """

    method: str
    path: str
    handler: str
    module: str
    kind: str
    bug_ref: str = ""
    reason: Optional[str] = None

    @property
    def location(self) -> str:
        return f"{self.module}:{self.handler}"

    @property
    def key(self) -> tuple:
        return (self.method.upper(), self.path)


# ===========================================================================
# IN SCOPE — the authz-sensitive surface guarded by EPIC-SEC Fase 2.
# ===========================================================================
# Grouped by hotspot. Each entry's `kind` mirrors how the *production* handler is
# actually protected (verified live by the signature guard).
IN_SCOPE: tuple[ScopeEntry, ...] = (
    # -------------------------------------------------------------------
    # routes_ai.py — chat-sessions (bug #2, the canonical IDOR exemplar).
    # All owner-checked via authz helpers loaded BEFORE any read/mutation.
    # -------------------------------------------------------------------
    ScopeEntry("POST", "/chat-sessions", "create_or_get_chat_session", "routes_ai", OWNER_CHECKED, "2"),
    ScopeEntry("GET", "/chat-sessions/{session_id}", "get_chat_session", "routes_ai", OWNER_CHECKED, "2"),
    ScopeEntry("GET", "/chat-sessions/{session_id}/messages", "get_session_messages", "routes_ai", OWNER_CHECKED, "2"),
    ScopeEntry("POST", "/chat-sessions/{session_id}/messages", "add_session_message", "routes_ai", OWNER_CHECKED, "2"),
    ScopeEntry("GET", "/chat-sessions/by-content/{content_id}", "get_session_by_content", "routes_ai", OWNER_CHECKED, "2"),
    ScopeEntry("GET", "/users/{user_id}/chat-sessions", "get_user_chat_sessions", "routes_ai", OWNER_CHECKED, "2"),
    ScopeEntry("PUT", "/chat-sessions/{session_id}/complete", "complete_chat_session", "routes_ai", OWNER_CHECKED, "2"),
    ScopeEntry("POST", "/chat-sessions/{session_id}/export-moodle", "export_session_moodle", "routes_ai", OWNER_CHECKED, "2"),

    # -------------------------------------------------------------------
    # routes_admin.py — notifications (bug #16).
    # -------------------------------------------------------------------
    ScopeEntry("GET", "/notifications/{user_id}/count", "notification_count", "routes_admin", OWNER_CHECKED, "16"),
    ScopeEntry("GET", "/notifications/{user_id}", "list_notifications", "routes_admin", OWNER_CHECKED, "16"),
    ScopeEntry("GET", "/users/{user_id}/notifications", "list_notifications", "routes_admin", OWNER_CHECKED, "16"),
    ScopeEntry("PUT", "/notifications/{notification_id}/read", "mark_read", "routes_admin", OWNER_CHECKED, "16"),
    ScopeEntry("PUT", "/notifications/{user_id}/read-all", "mark_all_read", "routes_admin", OWNER_CHECKED, "16"),
    ScopeEntry("DELETE", "/notifications/{notification_id}", "delete_notification", "routes_admin", OWNER_CHECKED, "16"),
    # create_notification: ADMIN-only system op; body.user_id is legitimate ONLY
    # because the role gate already proved the caller is privileged.
    ScopeEntry("POST", "/notifications", "create_notification", "routes_admin", ROLE_GATED, "16"),

    # -------------------------------------------------------------------
    # routes_admin.py — gamification (bug #14 / #62).
    # -------------------------------------------------------------------
    ScopeEntry("POST", "/users/{user_id}/activities", "create_activity", "routes_admin", OWNER_CHECKED, "14"),
    ScopeEntry(
        "POST", "/users/{user_id}/achievements/{achievement_id}/unlock",
        "unlock_achievement", "routes_admin", OWNER_CHECKED, "14",
    ),
    ScopeEntry("POST", "/users/{user_id}/certificates", "issue_certificate", "routes_admin", OWNER_CHECKED, "14"),
    ScopeEntry(
        "POST", "/users/{user_id}/courses/{course_id}/complete-content/{content_id}",
        "complete_content", "routes_admin", OWNER_CHECKED, "14",
    ),

    # -------------------------------------------------------------------
    # routes_admin.py — gamification READS (bug #14), remediated by SEC-READ-1.
    # Sibling reads of the write IDORs above. Each now calls
    # ``require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")``
    # before any read: a STUDENT reads ONLY their own, ADMIN/TEACHER may read
    # others. Moved out of KNOWN_UNREMEDIATED — the guard now enforces the fix.
    # -------------------------------------------------------------------
    ScopeEntry("GET", "/users/{user_id}/stats", "user_stats", "routes_admin", OWNER_CHECKED, "14"),
    ScopeEntry("GET", "/users/{user_id}/activities", "user_activities", "routes_admin", OWNER_CHECKED, "14"),
    ScopeEntry("GET", "/users/{user_id}/achievements", "user_achievements", "routes_admin", OWNER_CHECKED, "14"),
    ScopeEntry("GET", "/users/{user_id}/certificates", "user_certificates", "routes_admin", OWNER_CHECKED, "14"),
    ScopeEntry("GET", "/users/{user_id}/courses/{course_id}/progress", "user_course_progress", "routes_admin", OWNER_CHECKED, "14"),

    # -------------------------------------------------------------------
    # routes_admin.py — session review (bug #25).
    # create/update are TEACHER/ADMIN role-gated; get/reply owner-checked.
    # -------------------------------------------------------------------
    ScopeEntry("POST", "/chat-sessions/{session_id}/review", "create_review", "routes_admin", ROLE_GATED, "25"),
    ScopeEntry("GET", "/chat-sessions/{session_id}/review", "get_review", "routes_admin", OWNER_CHECKED, "25"),
    ScopeEntry("PUT", "/chat-sessions/{session_id}/review", "update_review", "routes_admin", ROLE_GATED, "25"),
    ScopeEntry("POST", "/chat-sessions/{session_id}/review/reply", "reply_review", "routes_admin", OWNER_CHECKED, "25"),

    # -------------------------------------------------------------------
    # main.py — avatar (bug #49).
    # -------------------------------------------------------------------
    ScopeEntry("POST", "/users/{user_id}/avatar", "upload_avatar", "main", OWNER_CHECKED, "49"),
)


# ===========================================================================
# ALLOWLIST — deliberate exceptions (every one carries a reason).
# ===========================================================================
# These routes are reachable with only ``Depends(get_current_user)`` (no role gate,
# no per-row owner check) BY DESIGN. The signature guard ignores ONLY what is listed
# here — there is no silent skip.
ALLOWLIST: tuple[ScopeEntry, ...] = (
    ScopeEntry(
        "POST", "/api/ai/socrates/dialogue", "ai_socrates_dialogue", "routes_ai",
        ALLOWLISTED, "2",
        reason=(
            "Socratic tutor carve-out (SEC-SCOPE-3): MUST stay reachable by STUDENT. "
            "It owns no per-user resource row to compare — identity (user_id passed to "
            "the AI service) is derived from current_user['id'], never from the body. "
            "Role-gating it would break the tutor for every student."
        ),
    ),
)


# ===========================================================================
# GUARDED PATH FAMILIES — the surface the anti-drift sweep polices.
# ===========================================================================
# The signature guard does NOT police the entire app (that would flag every
# authenticated catalog read and produce false positives that block legit PRs —
# explicitly called out as a risk in SEC-ADMIN-6). Instead it polices the route
# FAMILIES that contain the remediated IDORs. A NEW sibling added under any of
# these prefixes (the real regression vector) must be classified or it fails.
GUARDED_PATH_PREFIXES: tuple[str, ...] = (
    "/chat-sessions",
    "/notifications",
    "/users/{user_id}/activities",
    "/users/{user_id}/achievements",
    "/users/{user_id}/certificates",
    "/users/{user_id}/courses",
    "/users/{user_id}/notifications",
    "/users/{user_id}/chat-sessions",
    "/users/{user_id}/avatar",
)


# ===========================================================================
# KNOWN UNREMEDIATED — pre-existing gaps in guarded families, NOT fixed by
# SEC-ADMIN-2..5 / SEC-CHAT-* (they belong to follow-up stories).
# ===========================================================================
# These routes live in a guarded family but currently have NEITHER a role gate
# NOR a per-row owner check. They are recorded EXPLICITLY (never silently skipped)
# so:
#   * the guard stays green today (they are acknowledged debt, not new drift);
#   * QA sees the exact residual IDOR surface in one place;
#   * the list cannot GROW — a new unprotected sibling is NOT here, so it fails.
# When a follow-up story remediates one, MOVE it into IN_SCOPE (OWNER_CHECKED) and
# delete it from here; the guard then enforces the fix.
#
# >>> SECURITY DEBT (flagged for the QA gate): each of these reads/mutates another
# >>> user's data addressed only by a path/`user_id` with no ownership comparison.
KNOWN_UNREMEDIATED: tuple[ScopeEntry, ...] = (
    # The gamification READS (stats/activities/achievements/certificates/progress)
    # that used to live here were remediated by SEC-READ-1 and PROMOTED to
    # IN_SCOPE (OWNER_CHECKED). The guard now enforces their owner checks. The
    # only remaining record below is the notification_count path *alias*, whose
    # canonical route is already owner-checked.
    ScopeEntry("GET", "/users/{user_id}/notifications/count", "notification_count", "routes_admin", ROLE_GATED, "16",
               reason="Alias of notification_count; the canonical /notifications/{user_id}/count IS owner-checked. "
                      "This alias resolves to the SAME handler (owner-checked) — recorded for completeness."),
)
# NOTE on the `kind` field above: KNOWN_UNREMEDIATED reuses ScopeEntry purely as a
# record; the guard treats this tuple as an acknowledged-debt allowlist by HANDLER,
# independent of `kind`. The `reason` is the load-bearing field here.


# ---------------------------------------------------------------------------
# Convenience indexes (consumed by the guard test).
# ---------------------------------------------------------------------------
def _validate() -> None:
    """Internal sanity check on the registry's own integrity (fails import-time
    on a malformed entry so a typo can never weaken the guard)."""
    seen: set[tuple] = set()
    for e in IN_SCOPE + ALLOWLIST:
        assert e.kind in VALID_KINDS, f"{e.location}: invalid kind {e.kind!r}"
        if e.kind == ALLOWLISTED:
            assert e.reason, f"{e.location}: ALLOWLISTED entry must carry a reason"
        dup_key = (e.method.upper(), e.path, e.handler)
        assert dup_key not in seen, f"duplicate registry entry: {dup_key}"
        seen.add(dup_key)
    for e in KNOWN_UNREMEDIATED:
        assert e.reason and e.reason.strip(), (
            f"{e.location}: KNOWN_UNREMEDIATED entry MUST carry a reason "
            f"(acknowledged debt is never silent)"
        )


_validate()


def in_guarded_family(path: str) -> bool:
    """True if ``path`` belongs to a guarded route family (anti-drift surface)."""
    return any(
        path == p or path.startswith(p + "/") or path.startswith(p + "{")
        for p in GUARDED_PATH_PREFIXES
    )


# (method, path) -> ScopeEntry, for fast lookup against live routes.
BY_KEY: dict[tuple, ScopeEntry] = {e.key: e for e in IN_SCOPE}
ALLOWLIST_KEYS: frozenset[tuple] = frozenset(e.key for e in ALLOWLIST)
KNOWN_UNREMEDIATED_KEYS: frozenset[tuple] = frozenset(e.key for e in KNOWN_UNREMEDIATED)

# All handler names we consider "in the guarded surface" (in-scope + allowlisted),
# used to decide whether an unclassified live route is a real coverage gap.
GUARDED_HANDLERS: frozenset[str] = frozenset(
    e.handler for e in IN_SCOPE + ALLOWLIST
)
