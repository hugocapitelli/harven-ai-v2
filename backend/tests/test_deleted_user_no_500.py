"""GRD-5 it2 — None-guard on the two auth-path ``.maybe_single()`` sites the first
sweep missed (GRD5-1 auth.py, GRD5-2 main.py password reset).

Both hit the same supabase-py 2.28.x semantic: ``.maybe_single().execute()`` returns
``None`` (not ``_Result(data=None)``) on ZERO rows. Reading ``res.data`` unguarded →
AttributeError → HTTP 500.

  * GRD5-1 [ALTA] ``auth.get_current_user``: a VALID token whose ``sub`` points to a
    DELETED user 500'd on EVERY protected endpoint instead of returning 401.
  * GRD5-2 [MÉDIA] ``main.request_password_reset``: a non-existent email 500'd, which
    (500 vs the neutral 200) would also LEAK account existence — the anti-enumeration
    guarantee must be preserved (identical 200 for existing and non-existing emails).

These exercise the REAL dependency / route (no ``get_current_user`` override), minting a
genuine JWT signed with the seeded bootstrap secret. Runs headless via conftest's
faithful fake (0 rows → ``None``).
"""
from __future__ import annotations

import jwt
import pytest

from conftest import STRONG_SECRET


@pytest.fixture(autouse=True)
def _real_auth_dependency(app):
    """These tests exercise the REAL ``get_current_user`` (via a genuine Bearer token),
    so they must run WITHOUT any ``get_current_user`` override. ``main.app`` is a module
    singleton and the ``as_student``/``as_admin`` fixtures install an override that is
    NOT torn down, so it leaks across tests when they run in the same session. Pop it
    here to guarantee the real dependency runs. Also refresh the module-level JWT secret
    cache (rotation suites mutate it) so our token — signed with the seeded bootstrap
    secret — verifies deterministically regardless of test order."""
    from auth import get_current_user
    import jwt_secret_provider as provider

    app.dependency_overrides.pop(get_current_user, None)
    provider.invalidate_jwt_secret_cache()
    yield
    app.dependency_overrides.pop(get_current_user, None)
    provider.invalidate_jwt_secret_cache()


def _token(sub: str, role: str = "STUDENT") -> str:
    # Signed with the bootstrap secret the fake's system_settings seeds into
    # ``get_active_jwt_secret`` (jwt_secret starts NULL → seeded from env).
    return jwt.encode({"sub": sub, "role": role}, STRONG_SECRET, algorithm="HS256")


class TestDeletedUserIs401Not500:
    def test_valid_token_for_missing_user_is_401(self, client):
        # No dependency override → the REAL get_current_user runs. The token is valid
        # (correct signature) but its ``sub`` has no ``users`` row (deleted account).
        headers = {"Authorization": f"Bearer {_token('ghost-user-id')}"}
        resp = client.get("/dashboard/stats", headers=headers)
        assert resp.status_code == 401, (
            f"deleted-user token must be 401, not a 500 crash — got {resp.status_code}: {resp.text}"
        )

    def test_valid_token_for_existing_user_still_works(self, client):
        # Sanity: a token for a SEEDED user (admin-1) passes get_current_user and is
        # not blocked by the guard (proves the guard didn't over-reject).
        headers = {"Authorization": f"Bearer {_token('admin-1', 'ADMIN')}"}
        resp = client.get("/dashboard/stats", headers=headers)
        assert resp.status_code not in (401, 500), resp.text


class TestPasswordResetNonExistentEmailNo500:
    def test_reset_unknown_email_is_neutral_200_not_500(self, client):
        resp = client.post("/auth/request-reset", json={"email": "nobody@nowhere.test"})
        assert resp.status_code == 200, (
            f"reset for unknown email must be a neutral 200, not 500 — got {resp.status_code}: {resp.text}"
        )
        # Anti-enumeration: the body is the generic message, no token, no user id leaked.
        body = resp.json()
        assert "existir" in body.get("message", "")
        assert "token" not in body

    def test_reset_known_email_is_also_neutral_200(self, client):
        # Same neutral 200 for a SEEDED email — existence must NOT be distinguishable
        # by status code (the whole point of the anti-enumeration response).
        resp = client.post("/auth/request-reset", json={"email": "admin-1@harven.ai"})
        assert resp.status_code == 200, resp.text
        assert "existir" in resp.json().get("message", "")
