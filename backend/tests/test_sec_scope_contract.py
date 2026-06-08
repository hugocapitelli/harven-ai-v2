"""SEC-SCOPE-7 — min-role contract test + negative regression suite.

SEC-SCOPE-1..4 added per-endpoint role gates to the AI surface (authoring →
TEACHER/ADMIN, estimate-cost → authenticated, /integrations/status → ADMIN, plus
the teacher-scoped stats/sessions/gradebook). Two systemic fragilities remained
uncovered until now:

  (a) the CRITICAL carve-out ``POST /api/ai/socrates/dialogue`` must stay reachable
      by ``STUDENT`` (it is the student's Socratic tutor) and must NEVER be elevated
      to TEACHER/ADMIN by accident;
  (b) nothing stopped a future refactor from silently reverting any gate, or adding
      a new AI authoring endpoint with no ``require_role`` at all.

This module converts "which endpoint requires which role" into a versioned contract
(``EXPECTED_MIN_ROLE``) and guards it three ways:

  1. POSITIVE — the privileged role reaches each gated endpoint; STUDENT reaches the
     tutor; an authenticated user reaches estimate-cost; ADMIN reaches /status.
  2. NEGATIVE — STUDENT (and anonymous where relevant) is rejected (401/403) on the
     gated endpoints, with NO side effect (no AIService call, no pricing read).
  3. DRIFT (meta-test) — the live route dependencies are introspected and compared
     to ``EXPECTED_MIN_ROLE``: a reverted gate OR a new authoring endpoint missing
     from the map fails the build. This mirrors SEC-ADMIN-6's anti-pattern guard.

Runs fully in-process on the seeded ``FakeSupabaseClient`` (no network/DB). Uses the
shared harness from ``conftest.py`` (never edited).
"""
from __future__ import annotations

import pytest

from conftest import ADMIN_ID, STUDENT_A_ID, TEACHER_ID  # noqa: F401 (clarity / seed ids)

# Role sentinels (mirror auth.require_role's upper-cased semantics).
TEACHER = "TEACHER"          # require_role("ADMIN","TEACHER","INSTRUCTOR")
ADMIN = "ADMIN"              # require_role("ADMIN")
STUDENT = "STUDENT"          # carve-out: reachable by any authenticated user
AUTHENTICATED = "AUTHENTICATED"  # any logged-in role (no specific role gate beyond auth)


# ===========================================================================
# THE CONTRACT — single source of truth for min-role per sensitive endpoint.
# ===========================================================================
# value semantics:
#   TEACHER       -> Depends(require_role("ADMIN","TEACHER","INSTRUCTOR"))
#   ADMIN         -> Depends(require_role("ADMIN"))
#   AUTHENTICATED -> any authenticated role; gated by require_role(...all roles incl STUDENT)
#                    OR a require_role covering the broad set — STUDENT must pass.
#   STUDENT       -> CARVE-OUT: get_current_user only; STUDENT must reach it (never role-gated).
EXPECTED_MIN_ROLE: dict[tuple[str, str], str] = {
    # ---- AI authoring (SEC-SCOPE-3): TEACHER/ADMIN/INSTRUCTOR ----
    ("POST", "/api/ai/creator/generate"): TEACHER,
    ("POST", "/api/ai/creator/suggest-chapters"): TEACHER,
    ("POST", "/api/ai/analyst/detect"): TEACHER,
    ("POST", "/api/ai/editor/edit"): TEACHER,
    ("POST", "/api/ai/tester/validate"): TEACHER,
    ("POST", "/api/ai/organizer/session"): TEACHER,
    ("POST", "/api/ai/organizer/prepare-export"): TEACHER,
    # ---- estimate-cost (SEC-SCOPE-3): was unauthenticated; now role-gated ----
    ("GET", "/api/ai/estimate-cost"): TEACHER,
    # ---- integrations status (SEC-SCOPE-4): ADMIN only ----
    ("GET", "/integrations/status"): ADMIN,
    # ---- CRITICAL carve-out: the student's Socratic tutor stays open ----
    ("POST", "/api/ai/socrates/dialogue"): STUDENT,
}

# The authoring endpoints whose family must be FULLY mapped (drift: a new sibling
# under /api/ai/{creator,analyst,editor,tester,organizer} must appear in the map).
AUTHORING_PREFIXES = (
    "/api/ai/creator",
    "/api/ai/analyst",
    "/api/ai/editor",
    "/api/ai/tester",
    "/api/ai/organizer",
)

# Endpoints whose denied call must produce NO side effect (no LLM, no pricing read).
NO_SIDE_EFFECT_NEGATIVE = [
    ("POST", "/api/ai/creator/generate", {"chapter_content": "x" * 50}),
    ("POST", "/api/ai/analyst/detect", {"text": "abc"}),
    ("POST", "/api/ai/editor/edit", {"orientador_response": "r"}),
    ("POST", "/api/ai/tester/validate", {"edited_response": "r"}),
]


# ===========================================================================
# Live-route introspection (shared with the SEC-ADMIN-6 guard's approach).
# ===========================================================================
def _iter_api_routes(app):
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if not path or not methods or getattr(r, "dependant", None) is None:
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):
                continue
            yield m.upper(), path, r


def _require_role_sets(route):
    """Return a list of the ``allowed`` role-sets for every require_role gate on the route."""
    sets = []

    def walk(dep):
        for sub in dep.dependencies:
            call = sub.call
            if getattr(call, "__qualname__", "") == "require_role.<locals>.dependency":
                freevars = call.__code__.co_freevars
                closure = call.__closure__ or ()
                vals = {n: c.cell_contents for n, c in zip(freevars, closure)}
                allowed = vals.get("allowed")
                if allowed is not None:
                    sets.append({str(r).upper() for r in allowed})
            walk(sub)

    walk(route.dependant)
    return sets


def _uses_get_current_user(route):
    found = []

    def walk(dep):
        for sub in dep.dependencies:
            if getattr(sub.call, "__qualname__", "") == "get_current_user":
                found.append(True)
            walk(sub)

    walk(route.dependant)
    return bool(found)


@pytest.fixture
def live_routes(app):
    return {(m, p): r for m, p, r in _iter_api_routes(app)}


# ===========================================================================
# POSITIVE — privileged role / authenticated / student carve-out reach endpoints.
# ===========================================================================
class TestPositiveContract:
    @pytest.mark.parametrize(
        "path,payload",
        [
            ("/api/ai/creator/generate", {"chapter_content": "x" * 50}),
            ("/api/ai/creator/suggest-chapters", {"chapter_content": "x" * 50}),
            ("/api/ai/analyst/detect", {"text": "some text"}),
            ("/api/ai/editor/edit", {"orientador_response": "resp"}),
            ("/api/ai/tester/validate", {"edited_response": "resp"}),
        ],
    )
    def test_teacher_reaches_authoring(self, client, as_teacher, path, payload):
        resp = client.post(path, json=payload)
        # TEACHER passes the role gate; downstream the (mock) AI svc may 200 or 503,
        # but it must NEVER be an authz block.
        assert resp.status_code not in (401, 403), f"{path} -> {resp.status_code}: {resp.text}"

    def test_authenticated_reaches_estimate_cost(self, client, as_teacher):
        resp = client.get("/api/ai/estimate-cost?prompt_tokens=10&completion_tokens=10")
        assert resp.status_code == 200, resp.text
        assert "estimated_cost_usd" in resp.json()

    def test_admin_reaches_integrations_status(self, client, as_admin):
        resp = client.get("/integrations/status")
        assert resp.status_code == 200, resp.text

    def test_student_reaches_socrates_tutor(self, client, as_student):
        # CARVE-OUT: the tutor must stay open to STUDENT. Not 401/403.
        resp = client.post(
            "/api/ai/socrates/dialogue",
            json={
                "student_message": "I have a question",
                "chapter_content": "chapter text",
                "initial_question": {"q": "?"},
            },
        )
        assert resp.status_code not in (401, 403), (
            f"socrates tutor must stay open to STUDENT, got {resp.status_code}: {resp.text}"
        )


# ===========================================================================
# NEGATIVE — STUDENT / anonymous rejected, with NO side effects.
# ===========================================================================
class TestNegativeRegression:
    AUTHORING = [
        ("/api/ai/creator/generate", {"chapter_content": "x" * 50}),
        ("/api/ai/creator/suggest-chapters", {"chapter_content": "x" * 50}),
        ("/api/ai/analyst/detect", {"text": "some text"}),
        ("/api/ai/editor/edit", {"orientador_response": "resp"}),
        ("/api/ai/tester/validate", {"edited_response": "resp"}),
    ]

    @pytest.mark.parametrize("path,payload", AUTHORING)
    def test_student_blocked_on_authoring(self, client, as_student, path, payload):
        resp = client.post(path, json=payload)
        assert resp.status_code in (401, 403), f"{path} -> {resp.status_code}: {resp.text}"

    def test_student_blocked_on_estimate_cost(self, client, as_student):
        resp = client.get("/api/ai/estimate-cost?prompt_tokens=10&completion_tokens=10")
        assert resp.status_code in (401, 403), resp.text

    def test_anonymous_blocked_on_estimate_cost(self, client):
        resp = client.get("/api/ai/estimate-cost?prompt_tokens=10&completion_tokens=10")
        assert resp.status_code in (401, 403), resp.text

    def test_student_blocked_on_integrations_status(self, client, as_student):
        resp = client.get("/integrations/status")
        assert resp.status_code in (401, 403), resp.text
        assert "sitename" not in resp.text.lower()

    def test_teacher_blocked_on_integrations_status(self, client, as_teacher):
        # status is ADMIN-only — a TEACHER must be rejected.
        resp = client.get("/integrations/status")
        assert resp.status_code in (401, 403), resp.text

    def test_anonymous_blocked_on_integrations_status(self, client):
        resp = client.get("/integrations/status")
        assert resp.status_code in (401, 403), resp.text

    @pytest.mark.parametrize("method,path,payload", NO_SIDE_EFFECT_NEGATIVE)
    def test_denied_authoring_has_no_ai_side_effect(self, client, as_student, monkeypatch, method, path, payload):
        # Spy on the AIService factory: a denied (403) request must short-circuit at
        # the role gate, BEFORE any AI service is constructed/called.
        import routes_ai

        called = {"hit": False}
        real = routes_ai.get_ai_service

        def _spy():
            called["hit"] = True
            return real()

        monkeypatch.setattr(routes_ai, "get_ai_service", _spy)
        resp = client.post(path, json=payload)
        assert resp.status_code in (401, 403), resp.text
        assert called["hit"] is False, f"{path}: AI service was invoked on a denied request"


# ===========================================================================
# DRIFT META-TEST — live wiring must match EXPECTED_MIN_ROLE.
# ===========================================================================
class TestRoleContractDrift:
    def test_every_mapped_endpoint_has_the_expected_gate(self, live_routes):
        """A reverted gate (or a min-role widened/narrowed) fails here."""
        failures = []
        for (method, path), expected in EXPECTED_MIN_ROLE.items():
            route = live_routes.get((method, path))
            if route is None:
                failures.append(f"{method} {path}: mapped endpoint is not mounted")
                continue

            role_sets = _require_role_sets(route)

            if expected == STUDENT:
                # CARVE-OUT: must NOT be role-gated, and must accept any auth user.
                if role_sets:
                    failures.append(
                        f"{method} {path}: tutor carve-out was role-gated {role_sets} — "
                        f"STUDENT would be locked out. Remove require_role."
                    )
                elif not _uses_get_current_user(route):
                    failures.append(f"{method} {path}: carve-out lost its get_current_user auth")
                continue

            if not role_sets:
                failures.append(
                    f"{method} {path}: expected min-role {expected} but the live route has "
                    f"NO require_role gate — gate reverted."
                )
                continue

            allowed = set().union(*role_sets)
            if expected == ADMIN:
                if allowed != {"ADMIN"}:
                    failures.append(
                        f"{method} {path}: expected ADMIN-only, live gate allows {sorted(allowed)}"
                    )
            elif expected == TEACHER:
                # TEACHER tier: must include TEACHER (and ADMIN), must NOT admit STUDENT.
                if "STUDENT" in allowed:
                    failures.append(
                        f"{method} {path}: TEACHER-tier gate must NOT admit STUDENT (got {sorted(allowed)})"
                    )
                if "TEACHER" not in allowed:
                    failures.append(
                        f"{method} {path}: TEACHER-tier gate lost TEACHER (got {sorted(allowed)})"
                    )
            elif expected == AUTHENTICATED:
                if "STUDENT" not in allowed:
                    failures.append(
                        f"{method} {path}: AUTHENTICATED endpoint must admit STUDENT (got {sorted(allowed)})"
                    )

        assert not failures, "SEC-SCOPE role contract drift:\n  " + "\n  ".join(failures)

    def test_no_unmapped_authoring_endpoint(self, live_routes):
        """A NEW AI authoring endpoint added without an EXPECTED_MIN_ROLE entry fails —
        new authoring surface must be classified (mandatory coverage, anti-drift)."""
        unmapped = []
        for (method, path), route in live_routes.items():
            if not any(path.startswith(pre) for pre in AUTHORING_PREFIXES):
                continue
            if (method, path) in EXPECTED_MIN_ROLE:
                continue
            unmapped.append(f"{method} {path}  ->  {route.endpoint.__module__}:{route.endpoint.__name__}")

        assert not unmapped, (
            "New AI authoring endpoint(s) missing from EXPECTED_MIN_ROLE — every authoring "
            "route MUST declare its min-role so a gate cannot be skipped silently:\n  "
            + "\n  ".join(unmapped)
        )

    def test_socrates_carveout_is_explicitly_student(self):
        """First-class protection: the contract itself must keep socrates = STUDENT.
        If someone 'tidies' the map to TEACHER, this fails before the tutor breaks."""
        assert EXPECTED_MIN_ROLE[("POST", "/api/ai/socrates/dialogue")] == STUDENT


# ===========================================================================
# FAIL-BEFORE / PASS-AFTER self-proof of the drift detector.
# ===========================================================================
class TestDriftDetectorSelfProof:
    def _synthetic_app(self, gate):
        from fastapi import Depends, FastAPI

        from auth import get_current_user, require_role

        app = FastAPI()

        if gate == "teacher":
            @app.post("/syn/authoring")
            async def syn(current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR"))):
                return {}
        elif gate == "student_open":
            @app.post("/syn/authoring")
            async def syn(current_user: dict = Depends(get_current_user)):  # reverted: no role gate
                return {}
        return app

    def _route(self, app, path):
        for r in app.routes:
            if getattr(r, "path", None) == path and getattr(r, "dependant", None) is not None:
                return r
        raise AssertionError("route not found")

    def test_detects_correct_teacher_gate(self):
        route = self._route(self._synthetic_app("teacher"), "/syn/authoring")
        sets = _require_role_sets(route)
        assert sets, "PASS-AFTER: a correctly gated authoring route exposes its require_role set"
        allowed = set().union(*sets)
        assert "TEACHER" in allowed and "STUDENT" not in allowed

    def test_detects_reverted_open_gate(self):
        route = self._route(self._synthetic_app("student_open"), "/syn/authoring")
        # FAIL-BEFORE: a reverted (un-gated) authoring route has NO require_role set,
        # which is exactly what the drift meta-test flags as a reverted gate.
        assert _require_role_sets(route) == []
        assert _uses_get_current_user(route)
