"""Coverage for BUG-7: admin-to-user notification send (``POST /notifications``).

Exercises the ADMIN-only single-recipient notification create endpoint used
by the new "Notificar" action in ``UserManagement.tsx`` — payload matches the
real backend schema ``NotificationCreate`` (``routes_admin.py``).

Reuses the shared harness from ``conftest.py`` (fake Supabase client,
deterministic seed identities, ``as_admin``/``as_student`` actor overrides).
"""
from __future__ import annotations

from conftest import STUDENT_A_ID


class TestAdminNotify:
    def test_admin_sends_notification_to_user(self, client, as_admin, fake_supabase):
        before = len(fake_supabase.rows("notifications"))

        res = client.post(
            "/notifications",
            json={
                "user_id": STUDENT_A_ID,
                "title": "Aviso importante",
                "message": "Sua matrícula foi atualizada.",
                "notification_type": "admin_message",
            },
        )

        assert res.status_code == 200 or res.status_code == 201
        after = fake_supabase.rows("notifications")
        assert len(after) == before + 1

        created = after[-1]
        assert created["user_id"] == STUDENT_A_ID
        assert created["title"] == "Aviso importante"

    def test_non_admin_forbidden_from_sending_notification(self, client, as_student):
        res = client.post(
            "/notifications",
            json={
                "user_id": STUDENT_A_ID,
                "title": "Aviso importante",
                "message": "Sua matrícula foi atualizada.",
                "notification_type": "admin_message",
            },
        )

        assert res.status_code == 403
