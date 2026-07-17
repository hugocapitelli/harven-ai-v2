"""P0 fix 1 — a user with ``status == 'blocked'`` must lose ALL access.

Before this fix the block was cosmetic: ``PUT /users/{id} {"status": "blocked"}``
mutated the row (BUG-1 suite), but neither ``/auth/login`` nor
``auth.get_current_user`` ever read the field — a blocked student kept logging in
and kept using every protected endpoint with a pre-existing token.

Two gates are pinned here:
  * ``POST /auth/login``: correct credentials on a blocked account → 403 (checked
    AFTER password verification, so wrong-password stays a neutral 401 and the
    block is never an account-probing oracle);
  * ``auth.get_current_user``: a VALID token whose ``sub`` is now blocked → 403 on
    every protected endpoint (kills tokens minted before the block).

Mirrors the real-dependency harness of ``test_deleted_user_no_500.py`` (genuine
JWT, no ``get_current_user`` override, headless fake).
"""
from __future__ import annotations

import jwt
import pytest

from conftest import STRONG_SECRET, STUDENT_A_ID


@pytest.fixture(autouse=True)
def _real_auth_dependency(app, fake_supabase, monkeypatch):
    """Run the REAL ``get_current_user`` (no override) — same pattern/rationale as
    ``test_deleted_user_no_500.py``: pop leaked overrides and refresh the module
    JWT-secret cache so our bootstrap-signed token verifies regardless of order.
    Additionally patch ``auth.get_supabase`` (bound at import time, missed by the
    conftest patches) so ``create_access_token`` on the SUCCESSFUL login path
    resolves the fake instead of demanding real Supabase credentials."""
    import auth
    from auth import get_current_user
    import jwt_secret_provider as provider

    monkeypatch.setattr(auth, "get_supabase", lambda: fake_supabase)
    app.dependency_overrides.pop(get_current_user, None)
    provider.invalidate_jwt_secret_cache()
    yield
    app.dependency_overrides.pop(get_current_user, None)
    provider.invalidate_jwt_secret_cache()


def _token(sub: str, role: str = "STUDENT") -> str:
    return jwt.encode({"sub": sub, "role": role}, STRONG_SECRET, algorithm="HS256")


def _block(fake_supabase, user_id: str) -> None:
    fake_supabase.table("users").update({"status": "blocked"}).eq("id", user_id).execute()


class TestBlockedUserLogin:
    def _seed_credentials(self, fake_supabase, ra: str = "RA-BLOCKED", password: str = "secret123"):
        from auth import hash_password

        fake_supabase.table("users").update(
            {"ra": ra, "password_hash": hash_password(password)}
        ).eq("id", STUDENT_A_ID).execute()
        return ra, password

    def test_blocked_user_cannot_login_even_with_correct_password(self, client, fake_supabase):
        ra, password = self._seed_credentials(fake_supabase)
        _block(fake_supabase, STUDENT_A_ID)

        resp = client.post("/auth/login", json={"ra": ra, "password": password})
        assert resp.status_code == 403, resp.text
        assert "bloqueado" in resp.json()["detail"].lower()

    def test_wrong_password_on_blocked_account_stays_neutral_401(self, client, fake_supabase):
        """The block check runs AFTER password verification — a wrong password must
        keep the generic 401, never leak the blocked state as a probing oracle."""
        ra, _ = self._seed_credentials(fake_supabase)
        _block(fake_supabase, STUDENT_A_ID)

        resp = client.post("/auth/login", json={"ra": ra, "password": "wrong-pass"})
        assert resp.status_code == 401, resp.text

    def test_active_user_still_logs_in(self, client, fake_supabase):
        ra, password = self._seed_credentials(fake_supabase)

        resp = client.post("/auth/login", json={"ra": ra, "password": password})
        assert resp.status_code == 200, resp.text
        assert resp.json()["user"]["id"] == STUDENT_A_ID


class TestBlockedUserTokenRejected:
    def test_existing_token_dies_when_user_is_blocked(self, client, fake_supabase):
        """A token minted BEFORE the block must be rejected on protected endpoints."""
        _block(fake_supabase, STUDENT_A_ID)
        headers = {"Authorization": f"Bearer {_token(STUDENT_A_ID)}"}

        resp = client.get(f"/users/{STUDENT_A_ID}", headers=headers)
        assert resp.status_code == 403, (
            f"blocked user's token must be rejected — got {resp.status_code}: {resp.text}"
        )
        assert "bloqueado" in resp.json()["detail"].lower()

    def test_non_blocked_user_token_still_works(self, client):
        """Sanity: users without status='blocked' (incl. rows with NO status field)
        pass the gate — the guard does not over-reject."""
        headers = {"Authorization": f"Bearer {_token(STUDENT_A_ID)}"}
        resp = client.get(f"/users/{STUDENT_A_ID}", headers=headers)
        assert resp.status_code == 200, resp.text
