"""Static IDOR regression guard (SEC-ADMIN-6).

This is the META-TEST that fails the build if any authz-sensitive handler reverts
to the IDOR anti-pattern — ``Depends(get_current_user)`` (in any parameter name,
including ``_user``) with neither a ``require_role`` gate NOR a per-row owner
check. It is a **fail-before / pass-after** guard: with SEC-ADMIN-2..5 and
SEC-CHAT-* applied it is green; reintroduce a bare ``_user`` on an in-scope route
and it goes red, citing ``module:handler``.

It complements the behavioural happy-path suite (``test_idor_callers_happy_path``):
the static layer proves *every in-scope route is classified and wired as declared*;
the behavioural layer proves the *runtime effect* (owner passes / cross actor
403-404 / body.user_id ignored). Neither alone is sufficient — together they are.

DESIGN
======
Ownership comparison happens *inside* the handler body (we don't know a resource's
owner until the row is loaded), so it cannot be proven 100% by signature
introspection. Per SEC-ADMIN-6's prescribed approach we therefore drive off the
explicit ``scope_registry``:

  1. Every in-scope route MUST appear in the registry (``IN_SCOPE``), classified as
     ROLE_GATED / OWNER_CHECKED / ALLOWLISTED. An in-scope route that is missing
     from the registry FAILS (no silent gaps; new endpoints join by default).
  2. The *live* FastAPI wiring must MATCH the classification:
       * ROLE_GATED    -> the route really carries a ``require_role`` dependency.
       * OWNER_CHECKED -> the route uses ``get_current_user`` (not role-gated) AND
                          the handler source calls a sanctioned ``authz`` helper.
       * ALLOWLISTED   -> exempt, but only because it is listed with a reason.
  3. The anti-pattern detector: any in-scope/guarded route that depends on
     ``get_current_user`` but is neither role-gated nor calls an authz helper and is
     not allowlisted FAILS with an actionable ``module:handler`` message.

Runs fully in-process against the imported ``main.app`` (no network/DB). The app
is imported via the shared ``app`` fixture from ``conftest.py`` (which sets a strong
JWT secret + dev env and overrides Supabase with the fake), so we never touch a
real key or database.
"""
from __future__ import annotations

import inspect
import re

import pytest

from scope_registry import (
    ALLOWLISTED,
    ALLOWLIST_KEYS,
    AUTHZ_HELPERS,
    BY_KEY,
    GUARDED_HANDLERS,
    IN_SCOPE,
    KNOWN_UNREMEDIATED_KEYS,
    OWNER_CHECKED,
    ROLE_GATED,
    ScopeEntry,
    in_guarded_family,
)


# ---------------------------------------------------------------------------
# Live-route introspection helpers
# ---------------------------------------------------------------------------
def _iter_method_routes(app):
    """Yield ``(method, path, route)`` for every concrete HTTP route in ``app``.

    A FastAPI route may answer several methods; we fan them out so each
    ``(method, path)`` is checked independently against the registry.
    """
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        endpoint = getattr(r, "endpoint", None)
        # Only FastAPI APIRoutes carry a `.dependant` (the introspectable dependency
        # tree). Starlette's built-in Routes (/openapi.json, /docs, static mounts)
        # do not and are not part of the authz surface — skip them.
        if not path or not methods or endpoint is None:
            continue
        if getattr(r, "dependant", None) is None:
            continue
        for m in methods:
            if m in ("HEAD", "OPTIONS"):  # auto-added by Starlette; not authz surface
                continue
            yield m.upper(), path, r


def _dependant_calls(dependant):
    """Recursively collect the ``__qualname__`` of every dependency call in a route."""
    names: list[str] = []
    for sub in dependant.dependencies:
        names.append(getattr(sub.call, "__qualname__", "") or getattr(sub.call, "__name__", ""))
        names.extend(_dependant_calls(sub))
    return names


def _has_role_gate(route) -> bool:
    """True if the route carries a ``require_role(...)`` dependency anywhere."""
    return any(
        q == "require_role.<locals>.dependency" for q in _dependant_calls(route.dependant)
    )


def _uses_get_current_user(route) -> bool:
    """True if the route depends on ``get_current_user`` (the JWT-proof dependency)."""
    return any(q == "get_current_user" for q in _dependant_calls(route.dependant))


# A handler may enforce ownership at the QUERY layer instead of via a helper:
# filtering on ``user_id`` by the authenticated ``current_user["id"]`` means the
# query can only ever touch the caller's own rows (e.g. get_session_by_content).
# That is a sound owner-check form — the WHERE clause IS the comparison — so we
# accept it alongside the named helpers.
_SELF_SCOPE_PATTERNS = (
    re.compile(r"""\.eq\(\s*["']user_id["']\s*,\s*current_user\s*\[\s*["']id["']\s*\]"""),
    re.compile(r"""\.eq\(\s*["']user_id["']\s*,\s*current_user\.get\(\s*["']id["']\s*\)"""),
)


def _handler_source(route) -> str:
    try:
        return inspect.getsource(route.endpoint)
    except (OSError, TypeError):
        return ""


def _handler_calls_authz_helper(route) -> bool:
    """True if the handler SOURCE enforces ownership in a sanctioned way.

    Ownership semantics can't be proven statically, but we CAN prove the handler
    either (a) delegates to the shared ``authz`` module (never re-implements
    ownership inline) or (b) self-scopes the query to the authenticated user.
    """
    src = _handler_source(route)
    if not src:
        return False
    if any(helper in src for helper in AUTHZ_HELPERS):
        return True
    return any(p.search(src) for p in _SELF_SCOPE_PATTERNS)


# ---------------------------------------------------------------------------
# Resolve the live route object for a registry key (method, path).
# ---------------------------------------------------------------------------
@pytest.fixture
def live_routes(app):
    """Map ``(method, path)`` -> route for the imported app (deduped, last wins)."""
    table = {}
    for method, path, route in _iter_method_routes(app):
        table[(method, path)] = route
    return table


# ===========================================================================
# (A) Registry completeness — every in-scope route is classified.
# ===========================================================================
def test_every_in_scope_route_exists_in_the_app(live_routes):
    """A registry entry that points at a non-existent route is dead weight that
    could mask a rename/removal. Every IN_SCOPE entry must resolve to a live route."""
    missing = [e for e in IN_SCOPE if e.key not in live_routes]
    assert not missing, (
        "scope_registry references routes that are not mounted on the app "
        "(renamed/removed without updating the registry):\n  "
        + "\n  ".join(f"{e.method} {e.path} ({e.location})" for e in missing)
    )


def test_no_unclassified_route_in_a_guarded_family(live_routes):
    """The core anti-drift assertion, scoped to the GUARDED route families.

    A new sibling added under a guarded prefix (``/chat-sessions``, ``/notifications``,
    ``/users/{user_id}/activities`` …) is the real regression vector: it silently
    joins the IDOR-prone surface. Every such route that uses ``get_current_user``
    without a role gate MUST be accounted for — registered (IN_SCOPE), allowlisted,
    a recorded known-unremediated gap, or demonstrably owner-checked in its source.
    Anything else FAILS, citing ``module:handler``.

    This is deliberately NOT app-wide: policing every authenticated catalog read
    (``/courses``, ``/disciplines``) would create false positives that block
    legitimate PRs (a calibration risk SEC-ADMIN-6 explicitly warns against).
    """
    offenders = []
    for (method, path), route in live_routes.items():
        if not in_guarded_family(path):
            continue
        if not _uses_get_current_user(route):
            continue
        if _has_role_gate(route):
            continue  # role gate IS the authorization
        key = (method, path)
        if key in BY_KEY or key in ALLOWLIST_KEYS or key in KNOWN_UNREMEDIATED_KEYS:
            continue  # accounted for (classified / allowlisted / acknowledged debt)
        if _handler_calls_authz_helper(route):
            continue  # owner-checked in body (helper or query self-scope), just unlisted
        # get_current_user, no role gate, in a guarded family, NOT accounted for,
        # and NO owner check in the source -> the IDOR anti-pattern, surfaced.
        offenders.append((method, path, route.endpoint.__name__, route.endpoint.__module__))

    assert not offenders, (
        "Unclassified authz-sensitive endpoint(s) in a guarded family "
        "(get_current_user, no require_role, no owner check, not in scope_registry). "
        "Add each to IN_SCOPE (OWNER_CHECKED), ALLOWLIST, or KNOWN_UNREMEDIATED with a "
        "reason — never leave authz coverage to chance:\n  "
        + "\n  ".join(f"{m} {p}  ->  {mod}:{fn}" for m, p, fn, mod in offenders)
    )


# ===========================================================================
# (B) Classification matches live wiring (parametrized per registry entry).
# ===========================================================================
@pytest.mark.parametrize("entry", IN_SCOPE, ids=lambda e: f"{e.method}:{e.path}:{e.handler}")
def test_in_scope_route_matches_its_classification(entry: ScopeEntry, live_routes):
    route = live_routes.get(entry.key)
    assert route is not None, f"{entry.location}: registered route {entry.method} {entry.path} is not mounted"

    if entry.kind == ROLE_GATED:
        assert _has_role_gate(route), (
            f"{entry.location} is registered ROLE_GATED but the live route "
            f"({entry.method} {entry.path}) has NO require_role dependency — a gate "
            f"was reverted. Restore Depends(require_role(...)) or reclassify."
        )
    elif entry.kind == OWNER_CHECKED:
        # Owner-checked routes authenticate with get_current_user (not role-gated)
        # and MUST delegate ownership to a sanctioned authz helper in the body.
        assert _uses_get_current_user(route), (
            f"{entry.location} is OWNER_CHECKED but the live route does not depend "
            f"on get_current_user — it cannot identify the actor to compare."
        )
        assert _handler_calls_authz_helper(route), (
            f"{entry.location} is OWNER_CHECKED but its handler source calls NONE of "
            f"the authz helpers {sorted(AUTHZ_HELPERS)}. This is the IDOR anti-pattern: "
            f"get_current_user accepted as mere JWT proof and never compared to the "
            f"resource owner. Re-add the owner check (assert_owner_or_role / "
            f"require_self_or_role / load_session_or_404)."
        )
    else:  # ALLOWLISTED
        pytest.fail(f"{entry.location}: ALLOWLISTED entries must live in ALLOWLIST, not IN_SCOPE")


# ===========================================================================
# (C) The `_user`-without-comparison anti-pattern detector (explicit).
# ===========================================================================
def test_underscore_user_param_without_owner_check_is_caught(live_routes):
    """Directly target the documented defect signature: a guarded handler that
    binds ``get_current_user`` to a throwaway parameter (named ``_user`` / ``_admin``
    / ``_`` …) and then neither role-gates nor compares an owner.

    A throwaway-named param is only legitimate when a ``require_role`` gate makes the
    identity genuinely unused for the authorization decision (the role IS the gate).
    Otherwise it is the canonical IDOR smell.
    """
    offenders = []
    for (method, path), route in live_routes.items():
        endpoint = route.endpoint
        # Only police the guarded surface (in-scope or allowlisted handlers).
        if endpoint.__name__ not in GUARDED_HANDLERS:
            continue
        if not _uses_get_current_user(route):
            continue

        try:
            params = inspect.signature(endpoint).parameters
        except (ValueError, TypeError):
            continue
        throwaway = [
            name for name in params
            if name.startswith("_")  # _user, _admin, _ ...
        ]
        if not throwaway:
            continue
        # A throwaway identity param is fine IFF a role gate authorizes the request.
        if _has_role_gate(route):
            continue
        # Or IFF the body still performs an owner check via an authz helper.
        if _handler_calls_authz_helper(route):
            continue
        offenders.append(
            f"{endpoint.__module__}:{endpoint.__name__} ({method} {path}) "
            f"binds get_current_user to throwaway param {throwaway!r} but neither "
            f"role-gates nor calls an authz helper — IDOR anti-pattern"
        )

    assert not offenders, "Reintroduced `_user`-without-comparison IDOR:\n  " + "\n  ".join(offenders)


# ===========================================================================
# (D) The allowlist is honest — every exemption is justified.
# ===========================================================================
def test_allowlist_entries_are_justified(live_routes):
    """No silent skips: each allowlisted route must (1) exist live and (2) carry a
    non-empty reason. The Socratic tutor carve-out is the canonical legitimate case."""
    from scope_registry import ALLOWLIST

    for e in ALLOWLIST:
        assert e.kind == ALLOWLISTED, f"{e.location}: ALLOWLIST entry must be kind ALLOWLISTED"
        assert e.reason and e.reason.strip(), f"{e.location}: allowlisted route needs a documented reason"
        assert e.key in live_routes, (
            f"{e.location}: allowlisted route {e.method} {e.path} is not mounted — "
            f"a stale exemption could hide a real gap."
        )


# ===========================================================================
# (E) Fail-before / pass-after self-proof.
# ===========================================================================
# The guard is only valuable if it actually flips RED when a gate is reverted.
# We prove the *detection logic itself* on a synthetic FastAPI app so the proof is
# deterministic and does not depend on mutating the real production module.
class TestGuardCatchesRegressions:
    def _build_app(self, include_reverted: bool):
        from fastapi import Depends, FastAPI

        from auth import get_current_user
        from authz import assert_owner_or_role, load_session_or_404
        from database import get_supabase

        app = FastAPI()

        @app.get("/synthetic/{session_id}")
        async def synthetic_owner_checked(session_id: str, client=Depends(get_supabase),
                                          current_user: dict = Depends(get_current_user)):
            session = load_session_or_404(client, session_id)
            assert_owner_or_role(session.get("user_id"), current_user, "ADMIN")
            return session

        if include_reverted:
            # The IDOR anti-pattern: get_current_user bound to `_user`, no comparison.
            @app.get("/synthetic-reverted/{session_id}")
            async def synthetic_reverted(session_id: str, client=Depends(get_supabase),
                                         _user: dict = Depends(get_current_user)):
                return client.table("chat_sessions").select("*").eq("id", session_id).maybe_single().execute().data

        return app

    def _route(self, app, path):
        for r in app.routes:
            if getattr(r, "path", None) == path and getattr(r, "dependant", None) is not None:
                return r
        raise AssertionError(f"route {path} not found")

    def test_owner_checked_handler_passes_detection(self):
        app = self._build_app(include_reverted=False)
        route = self._route(app, "/synthetic/{session_id}")
        assert _uses_get_current_user(route)
        assert not _has_role_gate(route)
        # PASS-AFTER: a correctly owner-checked handler is recognized as protected.
        assert _handler_calls_authz_helper(route), "owner-checked handler must be detected as protected"

    def test_reverted_handler_is_detected_as_unprotected(self):
        app = self._build_app(include_reverted=True)
        route = self._route(app, "/synthetic-reverted/{session_id}")
        assert _uses_get_current_user(route)
        assert not _has_role_gate(route)
        # FAIL-BEFORE: the IDOR revert (no helper, no self-scope, `_user` param) is
        # flagged — _handler_calls_authz_helper returns False, which is exactly what
        # makes the OWNER_CHECKED / anti-pattern assertions go RED in CI.
        assert not _handler_calls_authz_helper(route), (
            "reverted IDOR handler must NOT be seen as protected — the guard would miss it"
        )
        params = inspect.signature(route.endpoint).parameters
        assert any(p.startswith("_") for p in params), "synthetic revert should use a throwaway `_user` param"
