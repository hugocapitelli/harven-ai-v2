"""Reusable 3-outcome IDOR assertion helpers for EPIC-SEC (SEC-ADMIN-2..5).

Every IDOR fix in this epic must satisfy the same 3-outcome contract, so the
assertions live here once and are imported by each consumer story:

  (1) the authenticated **owner** passes (2xx);
  (2) a **cross-tenant / cross-user actor** is rejected (403/404) AND no
      read-mutation lands on the other user's row;
  (3) a client-supplied **body.user_id** (or any forged identity field) is never
      trusted — the effective actor derives from the authenticated user.

These helpers operate on an `httpx`/`TestClient` response plus the
`FakeSupabaseClient` mutation log, so they work for any endpoint shape without
each story re-implementing the checks.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional

OK_STATUSES = frozenset({200, 201, 204})
DENY_STATUSES = frozenset({403, 404})


def _row_id_set(rows: Iterable[Dict[str, Any]]) -> set:
    return {str(r.get("id")) for r in rows if isinstance(r, dict) and r.get("id") is not None}


# ---------------------------------------------------------------------------
# (1) Owner passes
# ---------------------------------------------------------------------------
def assert_owner_passes(response) -> None:
    """The authenticated owner's request must succeed (2xx)."""
    assert response.status_code in OK_STATUSES, (
        f"owner expected 2xx, got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# (2) Cross actor forbidden AND no mutation
# ---------------------------------------------------------------------------
def assert_cross_actor_forbidden_no_mutation(
    response,
    fake,
    *,
    table: str,
    victim_row_id: str,
) -> None:
    """A cross-user actor must be denied (403/404) and leave the victim row intact.

    `fake` is the `FakeSupabaseClient`; its `.mutations` log is inspected to prove
    that no insert/update/delete touched `victim_row_id` in `table`. Call
    `fake.reset_mutations()` immediately before issuing the cross-actor request so
    only that request's writes are considered.
    """
    assert response.status_code in DENY_STATUSES, (
        f"cross actor expected 403/404, got {response.status_code}: {response.text}"
    )

    for m in fake.mutations:
        if m["table"] != table:
            continue
        touched = _row_id_set(m["rows"])
        assert str(victim_row_id) not in touched, (
            f"cross actor mutated victim row {victim_row_id!r} via {m['op']} on {table!r}"
        )
        # Also catch filter-targeted writes that may not echo the row id.
        for col, val in m["filters"]:
            assert not (col == "id" and str(val) == str(victim_row_id)), (
                f"cross actor issued {m['op']} filtered on victim id {victim_row_id!r}"
            )


# ---------------------------------------------------------------------------
# (3) body.user_id is never trusted
# ---------------------------------------------------------------------------
def assert_body_user_id_ignored(
    *,
    call: Callable[[Dict[str, Any]], Any],
    authenticated_user_id: str,
    forged_user_id: str,
    effective_user_id_of: Callable[[Any], Optional[str]],
) -> None:
    """Prove the effective actor derives from auth, not from a forged `body.user_id`.

    Args:
        call: invoked with a payload dict that already contains
            ``{"user_id": forged_user_id, ...}``; returns the response.
        authenticated_user_id: the id the request is authenticated as.
        forged_user_id: a *different* id planted in the body.
        effective_user_id_of: extracts the user_id the server actually used
            (e.g. from the response JSON or from the fake's resulting row).

    The endpoint must either reject the spoof (403/404) or honour the
    authenticated identity — never the forged body value.
    """
    assert str(authenticated_user_id) != str(forged_user_id), (
        "test setup error: forged id must differ from the authenticated id"
    )

    payload = {"user_id": forged_user_id}
    response = call(payload)

    if response.status_code in DENY_STATUSES:
        # Rejecting the spoof outright is an acceptable outcome.
        return

    assert response.status_code in OK_STATUSES, (
        f"expected the spoof to be ignored (2xx) or denied (403/404), "
        f"got {response.status_code}: {response.text}"
    )

    effective = effective_user_id_of(response)
    assert str(effective) == str(authenticated_user_id), (
        f"body.user_id was trusted: effective actor {effective!r} matched the "
        f"forged body value {forged_user_id!r} instead of the authenticated "
        f"user {authenticated_user_id!r}"
    )
    assert str(effective) != str(forged_user_id), (
        f"body.user_id {forged_user_id!r} leaked through as the effective actor"
    )
