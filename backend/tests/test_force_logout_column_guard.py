"""P2 fix 8 — force-logout must not claim success when the rotation didn't land.

On a DB without the SEC-ROT migration the ``jwt_secret`` column doesn't exist:
the UPDATE fails (or a lenient PostgREST silently drops the unknown key) and the
old code STILL answered "todos os tokens foram invalidados" — a false sense of
security for an ADMIN killing a leaked token. Pinned here:

  * missing column → actionable 500 naming the migration, never a fake success;
  * silent-drop (update "succeeds" but nothing persists) → read-back verification
    catches it → 500 stating no token was invalidated;
  * healthy path still rotates, verifies and reports success.
"""
from __future__ import annotations


def _strict(fake_supabase, monkeypatch, *, mode: str):
    """mode='missing-column' → update raises; mode='silent-drop' → update drops
    the jwt_secret key without error."""
    original_table = fake_supabase.table

    def table(name):
        qb = original_table(name)
        if name != "system_settings":
            return qb
        orig = qb.execute

        def execute():
            if qb._op == "update" and "jwt_secret" in (qb._payload or {}):
                if mode == "missing-column":
                    raise Exception(
                        "column system_settings.jwt_secret does not exist (42703)"
                    )
                if mode == "silent-drop":
                    qb._payload = {
                        k: v for k, v in qb._payload.items() if k != "jwt_secret"
                    }
            return orig()

        qb.execute = execute
        return qb

    monkeypatch.setattr(fake_supabase, "table", table)


class TestForceLogoutGuard:
    def test_missing_column_is_actionable_500_not_fake_success(
        self, client, as_admin, fake_supabase, monkeypatch
    ):
        _strict(fake_supabase, monkeypatch, mode="missing-column")
        resp = client.post("/admin/force-logout")
        assert resp.status_code == 500, resp.text
        assert "jwt_secret" in resp.json()["detail"]
        assert "migration" in resp.json()["detail"].lower()

    def test_silent_drop_is_caught_by_readback(self, client, as_admin, fake_supabase, monkeypatch):
        _strict(fake_supabase, monkeypatch, mode="silent-drop")
        resp = client.post("/admin/force-logout")
        assert resp.status_code == 500, resp.text
        assert "Nenhum token foi invalidado" in resp.json()["detail"]

    def test_healthy_rotation_still_succeeds(self, client, as_admin, fake_supabase):
        old = fake_supabase.rows("system_settings")[0].get("jwt_secret")
        resp = client.post("/admin/force-logout")
        assert resp.status_code == 200, resp.text
        new = fake_supabase.rows("system_settings")[0].get("jwt_secret")
        assert new and new != old
