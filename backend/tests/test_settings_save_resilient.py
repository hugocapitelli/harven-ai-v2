"""P0 fix 6 — POST /admin/settings must not lose ALL fields over one bad column.

The admin UI posts a free-form dict; PostgREST rejects an entire batch UPDATE if
any single key is not a column of ``system_settings`` — so one stray field made
the whole save fail and every valid setting was silently dropped. The fix keeps
the 1-round-trip batch on the happy path and, on failure, retries field-by-field:
valid fields persist, unknown ones are skipped (logged), and only an ALL-bad
payload is a 400.
"""
from __future__ import annotations


def _install_strict_columns(fake_supabase, monkeypatch, allowed: set[str]):
    """Emulate PostgREST: an UPDATE on system_settings containing any key outside
    ``allowed`` fails as a whole (unknown column)."""
    original_table = fake_supabase.table

    def table(name):
        qb = original_table(name)
        if name != "system_settings":
            return qb
        orig = qb.execute

        def execute():
            if qb._op == "update":
                for key in qb._payload:
                    if key not in allowed:
                        raise Exception(
                            f'column system_settings.{key} does not exist (PGRST204)'
                        )
            return orig()

        qb.execute = execute
        return qb

    monkeypatch.setattr(fake_supabase, "table", table)


ALLOWED = {"platform_name", "support_email", "jwt_secret", "jwt_secret_rotated_at"}


class TestResilientSettingsSave:
    def test_happy_path_batch_still_works(self, client, as_admin, fake_supabase, monkeypatch):
        _install_strict_columns(fake_supabase, monkeypatch, ALLOWED)

        resp = client.post("/admin/settings", json={"platform_name": "Harven X"})
        assert resp.status_code == 200, resp.text
        row = fake_supabase.rows("system_settings")[0]
        assert row["platform_name"] == "Harven X"

    def test_one_bad_field_does_not_kill_the_valid_ones(self, client, as_admin, fake_supabase, monkeypatch):
        _install_strict_columns(fake_supabase, monkeypatch, ALLOWED)

        resp = client.post(
            "/admin/settings",
            json={
                "platform_name": "Harven Resiliente",
                "support_email": "suporte@harven.ai",
                "campo_que_nao_existe": "valor",
            },
        )
        assert resp.status_code == 200, resp.text

        row = fake_supabase.rows("system_settings")[0]
        assert row["platform_name"] == "Harven Resiliente"
        assert row["support_email"] == "suporte@harven.ai"
        assert "campo_que_nao_existe" not in row

    def test_all_bad_fields_is_a_clear_400(self, client, as_admin, fake_supabase, monkeypatch):
        _install_strict_columns(fake_supabase, monkeypatch, ALLOWED)

        resp = client.post(
            "/admin/settings",
            json={"fantasma_1": "x", "fantasma_2": "y"},
        )
        assert resp.status_code == 400, resp.text
        detail = resp.json()["detail"]
        assert "fantasma_1" in detail and "fantasma_2" in detail

    def test_skipped_fields_are_audit_logged(self, client, as_admin, fake_supabase, monkeypatch):
        _install_strict_columns(fake_supabase, monkeypatch, ALLOWED)

        client.post(
            "/admin/settings",
            json={"platform_name": "Com Log", "campo_invalido": "x"},
        )
        logs = fake_supabase.rows("system_logs")
        assert any("campo_invalido" in (l.get("message") or "") for l in logs)
