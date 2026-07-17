"""P0 fix 4 — ``PUT /users/me``: self-service profile/password update.

Before this endpoint the only user-write path was ``PUT /users/{id}`` behind
``require_role("ADMIN")`` — a student could not fix their own name/email nor
rotate their own password. Pinned here:

  * any authenticated user updates own name/email (no ADMIN required);
  * password change REQUIRES a correct ``current_password`` (400 missing / 403 wrong);
  * privilege fields (``role``/``status``) in the payload are ignored, never applied;
  * identity comes from the token — the route updates ONLY the caller's row;
  * the literal ``me`` path wins over ``/users/{user_id}`` (no 403 from the
    ADMIN-only route, no ghost lookup of a user with id="me").
"""
from __future__ import annotations

from conftest import STUDENT_A_ID


def _seed_password(fake_supabase, password: str = "oldpass123") -> None:
    from auth import hash_password

    fake_supabase.table("users").update(
        {"password_hash": hash_password(password)}
    ).eq("id", STUDENT_A_ID).execute()


class TestProfileUpdate:
    def test_student_updates_own_name_and_email(self, client, as_student, fake_supabase):
        resp = client.put("/users/me", json={"name": "Novo Nome", "email": "novo@harven.ai"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "Novo Nome"
        assert body["email"] == "novo@harven.ai"
        assert "password_hash" not in body

        row = fake_supabase.find("users", id=STUDENT_A_ID)
        assert row["name"] == "Novo Nome"
        assert row["email"] == "novo@harven.ai"

    def test_empty_payload_is_400(self, client, as_student):
        resp = client.put("/users/me", json={})
        assert resp.status_code == 400

    def test_role_and_status_in_payload_are_ignored(self, client, as_student, fake_supabase):
        """Privilege escalation attempt: extra fields are dropped, not applied."""
        resp = client.put(
            "/users/me",
            json={"name": "Só o Nome", "role": "ADMIN", "status": "active"},
        )
        assert resp.status_code == 200, resp.text
        row = fake_supabase.find("users", id=STUDENT_A_ID)
        assert row["role"] == "STUDENT"
        assert row["name"] == "Só o Nome"

    def test_requires_authentication(self, client, app):
        # `main.app` is a module singleton and actor fixtures never tear their
        # override down — pop it so the REAL auth dependency runs here.
        from auth import get_current_user

        app.dependency_overrides.pop(get_current_user, None)
        resp = client.put("/users/me", json={"name": "X"})
        # No Bearer token → HTTPBearer rejects before the handler runs.
        assert resp.status_code in (401, 403)


class TestPasswordChange:
    def test_password_change_requires_current_password(self, client, as_student, fake_supabase):
        _seed_password(fake_supabase)
        resp = client.put("/users/me", json={"password": "newpass456"})
        assert resp.status_code == 400
        assert "current_password" in resp.json()["detail"]

    def test_wrong_current_password_is_403(self, client, as_student, fake_supabase):
        from auth import verify_password

        _seed_password(fake_supabase)
        resp = client.put(
            "/users/me",
            json={"password": "newpass456", "current_password": "wrong"},
        )
        assert resp.status_code == 403
        # The stored hash was NOT rotated.
        row = fake_supabase.find("users", id=STUDENT_A_ID)
        assert verify_password("oldpass123", row["password_hash"])

    def test_correct_current_password_rotates_hash(self, client, as_student, fake_supabase):
        from auth import verify_password

        _seed_password(fake_supabase)
        resp = client.put(
            "/users/me",
            json={"password": "newpass456", "current_password": "oldpass123"},
        )
        assert resp.status_code == 200, resp.text
        row = fake_supabase.find("users", id=STUDENT_A_ID)
        assert verify_password("newpass456", row["password_hash"])
        assert not verify_password("oldpass123", row["password_hash"])

    def test_short_new_password_is_422(self, client, as_student, fake_supabase):
        _seed_password(fake_supabase)
        resp = client.put(
            "/users/me",
            json={"password": "123", "current_password": "oldpass123"},
        )
        assert resp.status_code == 422


class TestRoutePrecedence:
    def test_me_does_not_fall_into_admin_only_param_route(self, client, as_student):
        """A STUDENT hitting /users/me must reach the self-service handler — if the
        param route swallowed it, require_role(ADMIN) would answer 403."""
        resp = client.put("/users/me", json={"name": "Precedence Check"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == STUDENT_A_ID
