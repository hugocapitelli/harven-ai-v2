"""Coverage for BUG-1: ``PUT /users/{id}`` status (block/unblock) and
``DELETE /users/{id}`` (admin user removal).

Before this fix, ``UserUpdate`` had no ``status`` field, so a PUT with only
``{"status": "blocked"}`` produced an empty update dict via
``_build_update_dict`` and 400'd with "Nenhum campo para atualizar" — the
block/unblock button in ``UserManagement.tsx`` never actually worked. This
adds the field (with a strict active/blocked validator) and exercises the
existing ``DELETE /users/{id}`` route (self-delete guard, 404s), which had no
prior test coverage.

Reuses the shared harness from ``conftest.py`` (fake Supabase client,
deterministic seed identities, ``as_admin`` actor override) — no new
fixtures, no network.
"""
from __future__ import annotations

from conftest import ADMIN_ID, STUDENT_A_ID, STUDENT_B_ID


class TestUpdateUserStatus:
    def test_admin_blocks_user_status_only_payload(self, client, as_admin, fake_supabase):
        """PUT with only {status:'blocked'} must mutate the row and return 200 —
        the empty-dict-400 regression this test guards against."""
        res = client.put(f"/users/{STUDENT_A_ID}", json={"status": "blocked"})

        assert res.status_code == 200
        assert res.json()["status"] == "blocked"

        row = next(r for r in fake_supabase.rows("users") if r["id"] == STUDENT_A_ID)
        assert row["status"] == "blocked"

    def test_admin_unblocks_user(self, client, as_admin):
        client.put(f"/users/{STUDENT_A_ID}", json={"status": "blocked"})
        res = client.put(f"/users/{STUDENT_A_ID}", json={"status": "active"})

        assert res.status_code == 200
        assert res.json()["status"] == "active"

    def test_invalid_status_value_is_rejected(self, client, as_admin):
        res = client.put(f"/users/{STUDENT_A_ID}", json={"status": "invalid"})

        assert res.status_code in (400, 422)


class TestDeleteUser:
    def test_admin_deletes_other_user(self, client, as_admin, fake_supabase):
        before = len(fake_supabase.rows("users"))

        res = client.delete(f"/users/{STUDENT_B_ID}")

        assert res.status_code in (200, 204)
        after = fake_supabase.rows("users")
        assert len(after) == before - 1
        assert all(r["id"] != STUDENT_B_ID for r in after)

    def test_admin_cannot_delete_self(self, client, as_admin, fake_supabase):
        before = len(fake_supabase.rows("users"))

        res = client.delete(f"/users/{ADMIN_ID}")

        assert res.status_code == 403
        assert len(fake_supabase.rows("users")) == before

    def test_delete_missing_user_returns_404(self, client, as_admin):
        res = client.delete("/users/does-not-exist")

        assert res.status_code == 404
