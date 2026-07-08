"""Coverage for ``POST /notifications/broadcast`` (DEBT-BROADCAST).

The Ação Global modal in ``AdminConsole.tsx`` was calling ``notificationsApi.create``
with a shape the backend never accepted (single-recipient ``NotificationCreate``
posing as a fan-out call), so every "Ação Global" click 422'd. This adds the
dedicated ADMIN-only broadcast endpoint and its regression coverage:

* ADMIN target=all fans out to every seeded user, one notification row each.
* target=<role> scopes the fan-out to that role only.
* STUDENT/TEACHER actors are forbidden (403) — mirrors ``create_notification``'s
  ADMIN-only gate (SEC-ADMIN-3).
* Missing ``title``/``message`` is a 422 (Pydantic validation), not a 500.

Reuses the shared harness from ``conftest.py`` (fake Supabase client, deterministic
seed identities, ``as_*`` actor overrides) — no new fixtures, no network.
"""
from __future__ import annotations

from conftest import ADMIN_ID, STUDENT_A_ID, STUDENT_B_ID, TEACHER_ID


class TestBroadcastAll:
    def test_admin_broadcast_all_sends_to_every_seeded_user(self, client, as_admin, fake_supabase):
        before = len(fake_supabase.rows("notifications"))

        res = client.post(
            "/notifications/broadcast",
            json={"title": "Comunicado", "message": "Manutenção às 22h.", "target": "all"},
        )

        assert res.status_code == 200
        body = res.json()
        seeded_users = fake_supabase.rows("users")
        assert body["sent"] == len(seeded_users)

        after = fake_supabase.rows("notifications")
        assert len(after) == before + len(seeded_users)

        # One row per seeded user, carrying the broadcast title/message.
        recipient_ids = {r["user_id"] for r in after[-len(seeded_users):]}
        assert recipient_ids == {u["id"] for u in seeded_users}
        assert all(r["title"] == "Comunicado" for r in after[-len(seeded_users):])
        assert all(r["message"] == "Manutenção às 22h." for r in after[-len(seeded_users):])


class TestBroadcastTargeted:
    def test_admin_broadcast_target_student_only_hits_student_role(self, client, as_admin, fake_supabase):
        before = len(fake_supabase.rows("notifications"))

        res = client.post(
            "/notifications/broadcast",
            json={"title": "Aviso", "message": "Prova amanhã.", "target": "student"},
        )

        assert res.status_code == 200
        body = res.json()
        # Seed has exactly 2 STUDENT users (STUDENT_A_ID, STUDENT_B_ID).
        assert body["sent"] == 2

        after = fake_supabase.rows("notifications")
        assert len(after) == before + 2
        new_rows = after[-2:]
        recipient_ids = {r["user_id"] for r in new_rows}
        assert recipient_ids == {STUDENT_A_ID, STUDENT_B_ID}
        # Neither the teacher nor the admin received a row from this call.
        assert TEACHER_ID not in recipient_ids
        assert ADMIN_ID not in recipient_ids


class TestBroadcastForbidden:
    def test_student_cannot_broadcast(self, client, as_student):
        res = client.post(
            "/notifications/broadcast",
            json={"title": "X", "message": "Y", "target": "all"},
        )
        assert res.status_code == 403

    def test_teacher_cannot_broadcast(self, client, as_teacher):
        res = client.post(
            "/notifications/broadcast",
            json={"title": "X", "message": "Y", "target": "all"},
        )
        assert res.status_code == 403


class TestBroadcastValidation:
    def test_missing_title_is_422(self, client, as_admin):
        res = client.post(
            "/notifications/broadcast",
            json={"message": "sem titulo", "target": "all"},
        )
        assert res.status_code == 422

    def test_missing_message_is_422(self, client, as_admin):
        res = client.post(
            "/notifications/broadcast",
            json={"title": "sem mensagem", "target": "all"},
        )
        assert res.status_code == 422
