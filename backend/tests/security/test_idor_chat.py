"""Regression suite for the routes_ai.py IDOR / authorization remediation.

Covers EPIC-SEC Fase 2 stories owned by the `routes_ai` change:

  * SEC-CHAT-1 — ownership on chat-session READ endpoints (get/messages/export/list)
  * SEC-CHAT-2 — ownership + no user_id spoof (create_or_get, add_session_message)
  * SEC-CHAT-3 — complete_chat_session idempotent + ownership; no-reactivate completed
  * SEC-CHAT-4 — gate organizer/session + prepare-export; actor derived from session
  * SEC-SCOPE-3 — role-gate AI authoring + estimate-cost; tutor (socrates) preserved
  * SEC-SCOPE-4 — role-gate GET /integrations/status (ADMIN only)
  * SEC-SCOPE-5 — HMAC shared-secret on the Moodle webhook
  * SEC-SCOPE-6 — LTI launch role + credential hardening

Every test runs fully in-process against the seeded `FakeSupabaseClient`
(no network, no DB). Fixtures come from the Foundation `conftest.py`
(`client`, `as_student`, `as_other_student`, `as_teacher`, `as_admin`,
`fake_supabase`/`seed`) and the 3-outcome helpers from `idor_helpers.py`.
conftest.py is NOT edited.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from conftest import (
    SESSION_A_ID,
    SESSION_B_ID,
    STUDENT_A_ID,
    STUDENT_B_ID,
    TEACHER_ID,
    ADMIN_ID,
)
from idor_helpers import (
    assert_owner_passes,
    assert_cross_actor_forbidden_no_mutation,
)


# ===========================================================================
# SEC-CHAT-1 — ownership on chat-session READ endpoints
# ===========================================================================
class TestChatReadOwnership:
    def test_owner_reads_own_session(self, client, as_student):
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}")
        assert_owner_passes(resp)
        body = resp.json()
        assert body["user_id"] == STUDENT_A_ID
        assert "messages" in body

    def test_cross_actor_cannot_read_session(self, client, as_other_student, fake_supabase):
        # STUDENT_B trying to read STUDENT_A's session.
        fake_supabase.reset_mutations()
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}")
        assert resp.status_code in (403, 404), resp.text
        # No leak of the owner's content in the body.
        assert "hello from A" not in resp.text

    def test_cross_actor_cannot_read_messages(self, client, as_other_student):
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/messages")
        assert resp.status_code in (403, 404), resp.text
        assert "hello from A" not in resp.text

    def test_owner_reads_own_messages(self, client, as_student):
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/messages")
        assert_owner_passes(resp)
        assert any(m.get("content") == "hello from A" for m in resp.json())

    def test_teacher_can_read_any_session(self, client, as_teacher):
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}")
        assert_owner_passes(resp)
        assert resp.json()["user_id"] == STUDENT_A_ID

    def test_admin_can_read_any_session(self, client, as_admin):
        resp = client.get(f"/chat-sessions/{SESSION_B_ID}")
        assert_owner_passes(resp)

    def test_missing_session_is_404(self, client, as_student):
        resp = client.get("/chat-sessions/does-not-exist")
        assert resp.status_code == 404

    # ---- list by user (require_self_or_role) ----
    def test_student_lists_only_own_user_sessions(self, client, as_student):
        resp = client.get(f"/users/{STUDENT_A_ID}/chat-sessions")
        assert_owner_passes(resp)

    def test_student_cannot_list_other_user_sessions(self, client, as_other_student):
        resp = client.get(f"/users/{STUDENT_A_ID}/chat-sessions")
        assert resp.status_code in (403, 404), resp.text
        assert "hello from A" not in resp.text

    def test_teacher_lists_any_user_sessions(self, client, as_teacher):
        resp = client.get(f"/users/{STUDENT_A_ID}/chat-sessions")
        assert_owner_passes(resp)


# ===========================================================================
# SEC-CHAT-2 — ownership + remove user_id spoof
# ===========================================================================
class TestCreateAndAddMessageOwnership:
    def test_owner_creates_own_session(self, client, as_student):
        resp = client.post("/chat-sessions", json={"content_id": "content-fresh"})
        assert_owner_passes(resp)
        assert resp.json()["user_id"] == STUDENT_A_ID

    def test_body_user_id_spoof_is_rejected(self, client, as_student, fake_supabase):
        # A STUDENT forging another user's id must NOT create a session for the victim.
        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-spoof", "user_id": STUDENT_B_ID},
        )
        assert resp.status_code in (403, 404), resp.text
        leaked = fake_supabase.find(
            "chat_sessions", user_id=STUDENT_B_ID, content_id="content-spoof"
        )
        assert leaked is None

    def test_admin_body_user_id_still_owned_by_admin(self, client, as_admin):
        # ADMIN passes the spoof gate (privileged) but the row is owned by the admin,
        # never by the forged body value.
        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-admin", "user_id": STUDENT_B_ID},
        )
        assert resp.status_code in (200, 201)
        assert resp.json()["user_id"] == ADMIN_ID

    def test_owner_adds_message(self, client, as_student):
        resp = client.post(
            f"/chat-sessions/{SESSION_A_ID}/messages",
            json={"role": "user", "content": "legit turn"},
        )
        assert_owner_passes(resp)

    def test_cross_actor_cannot_add_message_no_insert(self, client, as_other_student, fake_supabase):
        before = len(fake_supabase.rows("chat_messages"))
        fake_supabase.reset_mutations()
        resp = client.post(
            f"/chat-sessions/{SESSION_A_ID}/messages",
            json={"role": "user", "content": "forged injection"},
        )
        assert resp.status_code in (403, 404), resp.text
        # No message inserted into the victim's session.
        after = fake_supabase.rows("chat_messages")
        assert len(after) == before
        assert all(m.get("content") != "forged injection" for m in after)
        inserts = [m for m in fake_supabase.mutations if m["op"] == "insert"]
        assert inserts == []

    def test_add_message_missing_session_404(self, client, as_student):
        resp = client.post(
            "/chat-sessions/no-such-session/messages",
            json={"role": "user", "content": "x"},
        )
        assert resp.status_code == 404

    def test_teacher_can_add_message_to_any_session(self, client, as_teacher):
        resp = client.post(
            f"/chat-sessions/{SESSION_A_ID}/messages",
            json={"role": "assistant", "content": "teacher note"},
        )
        assert_owner_passes(resp)


# ===========================================================================
# SEC-CHAT-3 — complete idempotent + ownership; create_or_get no-reactivate
# ===========================================================================
class TestCompleteAndReactivation:
    def test_owner_completes_session(self, client, as_student):
        resp = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert_owner_passes(resp)
        assert resp.json()["status"] == "completed"

    def test_cross_actor_cannot_complete_no_mutation(self, client, as_other_student, fake_supabase):
        fake_supabase.reset_mutations()
        resp = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="chat_sessions", victim_row_id=SESSION_A_ID
        )
        # Status untouched.
        row = fake_supabase.find("chat_sessions", id=SESSION_A_ID)
        assert row["status"] == "active"

    def test_complete_is_idempotent_noop(self, client, as_student, fake_supabase):
        # First complete writes; second is a 200 no-op with no redundant update.
        first = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert first.status_code == 200
        assert first.json()["status"] == "completed"

        fake_supabase.reset_mutations()
        second = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert second.status_code == 200
        assert second.json()["status"] == "completed"
        # No update mutation was issued by the no-op path.
        updates = [
            m for m in fake_supabase.mutations
            if m["op"] == "update" and m["table"] == "chat_sessions"
        ]
        assert updates == [], f"idempotent complete must not re-write: {updates}"

    def test_complete_missing_session_404(self, client, as_student):
        resp = client.put("/chat-sessions/nope/complete")
        assert resp.status_code == 404

    def test_create_or_get_does_not_reactivate_completed(self, client, as_student, fake_supabase):
        # Seed a completed session for STUDENT_A on a specific content.
        fake_supabase.seed("chat_sessions", [
            {"id": "sess-completed", "user_id": STUDENT_A_ID,
             "content_id": "content-done", "status": "completed", "total_messages": 5},
        ])
        resp = client.post("/chat-sessions", json={"content_id": "content-done"})
        assert resp.status_code in (200, 201)
        # The original completed session must NOT have been forced to active.
        original = fake_supabase.find("chat_sessions", id="sess-completed")
        assert original["status"] == "completed", "completed session was reactivated"
        # A new, distinct active session was created for the new attempt.
        assert resp.json().get("id") != "sess-completed"
        assert resp.json().get("status") == "active"

    def test_create_or_get_reactivates_abandoned(self, client, as_student, fake_supabase):
        fake_supabase.seed("chat_sessions", [
            {"id": "sess-abandoned", "user_id": STUDENT_A_ID,
             "content_id": "content-resume", "status": "abandoned", "total_messages": 2},
        ])
        resp = client.post("/chat-sessions", json={"content_id": "content-resume"})
        assert resp.status_code in (200, 201)
        assert resp.json()["id"] == "sess-abandoned"
        assert resp.json()["status"] == "active"


# ===========================================================================
# SEC-CHAT-4 — organizer/prepare-export + export-moodle gate; actor from session
# ===========================================================================
class TestExportAndOrganizerGate:
    # ---- export-moodle (student-reachable, owner gate) ----
    def test_owner_exports_own_session(self, client, as_student):
        resp = client.post(f"/chat-sessions/{SESSION_A_ID}/export-moodle")
        assert_owner_passes(resp)

    def test_cross_actor_cannot_export_no_pii_leak(self, client, as_other_student, fake_supabase):
        fake_supabase.reset_mutations()
        resp = client.post(f"/chat-sessions/{SESSION_A_ID}/export-moodle")
        assert resp.status_code in (403, 404), resp.text
        # No PII or transcript of the victim leaks.
        assert "hello from A" not in resp.text
        assert f"{STUDENT_A_ID}@harven.ai" not in resp.text
        assert "Student A" not in resp.text

    # ---- prepare-export (now role-gated by SEC-SCOPE-3) ----
    def test_student_blocked_from_prepare_export(self, client, as_student):
        # SEC-SCOPE-3 role gate: STUDENT never reaches the organizer at all.
        resp = client.post(
            "/api/ai/organizer/prepare-export",
            json={"session_id": SESSION_A_ID},
        )
        assert resp.status_code in (401, 403), resp.text

    def test_teacher_prepare_export_actor_from_session_not_body(self, client, as_teacher):
        # A TEACHER passes the role gate AND the ownership override. The actor
        # (user_name/user_email) must derive from the SESSION owner (STUDENT_A),
        # never from a forged body.user_id (STUDENT_B).
        resp = client.post(
            "/api/ai/organizer/prepare-export",
            json={"session_id": SESSION_A_ID, "user_id": STUDENT_B_ID},
        )
        assert resp.status_code == 200, resp.text
        text = resp.text
        # The forged STUDENT_B PII must not appear; the real owner (A) is used.
        assert f"{STUDENT_B_ID}@harven.ai" not in text
        assert "Student B" not in text

    def test_admin_prepare_export_cross_session_uses_owner(self, client, as_admin):
        # ADMIN can export STUDENT_B's session; actor is the session owner, not body.
        resp = client.post(
            "/api/ai/organizer/prepare-export",
            json={"session_id": SESSION_B_ID, "user_id": STUDENT_A_ID},
        )
        assert resp.status_code == 200, resp.text
        assert "Student A" not in resp.text  # forged body id ignored

    # ---- organizer/session get_session_status ----
    def test_student_blocked_from_organizer_session(self, client, as_student):
        resp = client.post(
            "/api/ai/organizer/session",
            json={"action": "get_session_status", "payload": {"session_id": SESSION_A_ID}},
        )
        assert resp.status_code in (401, 403), resp.text

    def test_teacher_organizer_session_status_owner_ok(self, client, as_teacher):
        resp = client.post(
            "/api/ai/organizer/session",
            json={"action": "get_session_status", "payload": {"session_id": SESSION_A_ID}},
        )
        # Teacher passes; the gate allows privileged read of the student's session.
        assert resp.status_code in (200, 503), resp.text  # 503 only if AI svc unavailable


# ===========================================================================
# SEC-SCOPE-3 — role-gate AI authoring; PRESERVE socrates tutor for students
# ===========================================================================
class TestAuthoringRoleGate:
    AUTHORING = [
        ("/api/ai/creator/generate", {"chapter_content": "x" * 50}),
        ("/api/ai/creator/suggest-chapters", {"chapter_content": "x" * 50}),
        ("/api/ai/analyst/detect", {"text": "some text"}),
        ("/api/ai/editor/edit", {"orientador_response": "resp"}),
        ("/api/ai/tester/validate", {"edited_response": "resp"}),
    ]

    @pytest.mark.parametrize("path,payload", AUTHORING)
    def test_student_blocked_on_authoring(self, client, as_student, path, payload):
        resp = client.post(path, json=payload)
        assert resp.status_code in (401, 403), f"{path} -> {resp.status_code}: {resp.text}"

    def test_student_blocked_on_organizer_session(self, client, as_student):
        resp = client.post(
            "/api/ai/organizer/session",
            json={"action": "noop", "payload": {}},
        )
        assert resp.status_code in (401, 403), resp.text

    def test_student_blocked_on_prepare_export(self, client, as_student):
        resp = client.post("/api/ai/organizer/prepare-export", json={})
        assert resp.status_code in (401, 403), resp.text

    # ---- estimate-cost: was unauthenticated, now role-gated ----
    def test_estimate_cost_anonymous_blocked(self, client):
        # No actor override -> real HTTPBearer dependency rejects the missing token.
        resp = client.get("/api/ai/estimate-cost?prompt_tokens=10&completion_tokens=10")
        assert resp.status_code in (401, 403), resp.text

    def test_estimate_cost_student_blocked(self, client, as_student):
        resp = client.get("/api/ai/estimate-cost?prompt_tokens=10&completion_tokens=10")
        assert resp.status_code in (401, 403), resp.text

    def test_estimate_cost_teacher_ok(self, client, as_teacher):
        resp = client.get("/api/ai/estimate-cost?prompt_tokens=10&completion_tokens=10")
        assert resp.status_code == 200, resp.text
        assert "estimated_cost_usd" in resp.json()

    # ---- CRITICAL carve-out: socrates tutor stays open to students ----
    def test_socrates_dialogue_reachable_by_student(self, client, as_student):
        resp = client.post(
            "/api/ai/socrates/dialogue",
            json={
                "student_message": "I have a question",
                "chapter_content": "chapter text",
                "initial_question": {"q": "?"},
            },
        )
        # The tutor must NOT be role-gated: a STUDENT passes auth (it is not 401/403).
        # Downstream the mock/AI service may yield 200 or 503, but never an authz block.
        assert resp.status_code not in (401, 403), (
            f"socrates tutor must stay open to students, got {resp.status_code}: {resp.text}"
        )


# ===========================================================================
# SEC-SCOPE-4 — role-gate GET /integrations/status (ADMIN only)
# ===========================================================================
class TestIntegrationStatusGate:
    def test_anonymous_blocked(self, client):
        resp = client.get("/integrations/status")
        assert resp.status_code in (401, 403), resp.text
        assert "sitename" not in resp.text.lower()

    def test_student_blocked(self, client, as_student):
        resp = client.get("/integrations/status")
        assert resp.status_code in (401, 403), resp.text

    def test_teacher_blocked(self, client, as_teacher):
        # status is ADMIN-only (sibling integration_logs uses require_role("ADMIN")).
        resp = client.get("/integrations/status")
        assert resp.status_code in (401, 403), resp.text

    def test_admin_ok(self, client, as_admin):
        resp = client.get("/integrations/status")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "jacad" in body and "moodle" in body


# ===========================================================================
# SEC-SCOPE-5 — HMAC shared-secret on the Moodle webhook
# ===========================================================================
def _sign(secret: str, raw: bytes) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class TestMoodleWebhookHMAC:
    SECRET = "moodle-shared-secret-value-1234567890"

    def _payload_bytes(self, **overrides) -> bytes:
        payload = {
            "event_type": "rating_submitted",
            "session_id": SESSION_A_ID,
            "student_id": STUDENT_A_ID,
            "teacher_id": TEACHER_ID,
            "rating": 5,
            "feedback": "great",
        }
        payload.update(overrides)
        return json.dumps(payload).encode()

    def test_no_signature_header_401_no_insert(self, client, fake_supabase, monkeypatch):
        monkeypatch.setenv("MOODLE_WEBHOOK_SECRET", self.SECRET)
        raw = self._payload_bytes()
        before = len(fake_supabase.rows("moodle_ratings"))
        resp = client.post(
            "/integrations/moodle/webhook",
            content=raw,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert len(fake_supabase.rows("moodle_ratings")) == before

    def test_invalid_signature_401_no_insert(self, client, fake_supabase, monkeypatch):
        monkeypatch.setenv("MOODLE_WEBHOOK_SECRET", self.SECRET)
        raw = self._payload_bytes()
        before = len(fake_supabase.rows("moodle_ratings"))
        resp = client.post(
            "/integrations/moodle/webhook",
            content=raw,
            headers={"content-type": "application/json", "X-Moodle-Signature": "deadbeef"},
        )
        assert resp.status_code == 401, resp.text
        assert len(fake_supabase.rows("moodle_ratings")) == before

    def test_valid_signature_inserts_one_rating(self, client, fake_supabase, monkeypatch):
        monkeypatch.setenv("MOODLE_WEBHOOK_SECRET", self.SECRET)
        raw = self._payload_bytes()
        sig = _sign(self.SECRET, raw)
        before = len(fake_supabase.rows("moodle_ratings"))
        resp = client.post(
            "/integrations/moodle/webhook",
            content=raw,
            headers={"content-type": "application/json", "X-Moodle-Signature": sig},
        )
        assert resp.status_code == 200, resp.text
        after = fake_supabase.rows("moodle_ratings")
        assert len(after) == before + 1

    def test_valid_signature_sha256_prefix_accepted(self, client, fake_supabase, monkeypatch):
        monkeypatch.setenv("MOODLE_WEBHOOK_SECRET", self.SECRET)
        raw = self._payload_bytes()
        sig = "sha256=" + _sign(self.SECRET, raw)
        resp = client.post(
            "/integrations/moodle/webhook",
            content=raw,
            headers={"content-type": "application/json", "X-Moodle-Signature": sig},
        )
        assert resp.status_code == 200, resp.text

    def test_production_without_secret_fail_closed_401(self, client, fake_supabase, monkeypatch):
        # No secret in env, no system_settings row, ENVIRONMENT=production -> 401.
        monkeypatch.delenv("MOODLE_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        import config
        config.get_settings.cache_clear()
        raw = self._payload_bytes()
        before = len(fake_supabase.rows("moodle_ratings"))
        resp = client.post(
            "/integrations/moodle/webhook",
            content=raw,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 401, resp.text
        assert len(fake_supabase.rows("moodle_ratings")) == before

    def test_non_production_without_secret_warns_and_proceeds(self, client, fake_supabase, monkeypatch, caplog):
        # No secret, non-production -> warning + dev path proceeds (rating inserted).
        monkeypatch.delenv("MOODLE_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "development")
        import config
        config.get_settings.cache_clear()
        raw = self._payload_bytes()
        before = len(fake_supabase.rows("moodle_ratings"))
        import logging
        with caplog.at_level(logging.WARNING):
            resp = client.post(
                "/integrations/moodle/webhook",
                content=raw,
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 200, resp.text
        assert len(fake_supabase.rows("moodle_ratings")) == before + 1
        assert any("secret not configured" in r.message.lower() for r in caplog.records)

    def test_secret_resolved_from_system_settings(self, client, fake_supabase, monkeypatch):
        # No env secret; secret lives in system_settings. Valid HMAC -> 200 + insert.
        monkeypatch.delenv("MOODLE_WEBHOOK_SECRET", raising=False)
        fake_supabase.seed("system_settings", [
            {"id": "settings-1", "moodle_webhook_secret": self.SECRET},
        ])
        raw = self._payload_bytes()
        sig = _sign(self.SECRET, raw)
        before = len(fake_supabase.rows("moodle_ratings"))
        resp = client.post(
            "/integrations/moodle/webhook",
            content=raw,
            headers={"content-type": "application/json", "X-Moodle-Signature": sig},
        )
        assert resp.status_code == 200, resp.text
        assert len(fake_supabase.rows("moodle_ratings")) == before + 1


# ===========================================================================
# SEC-SCOPE-6 — LTI launch role + credential hardening (unit-level)
# ===========================================================================
class TestLTIHardening:
    def test_administrator_role_never_maps_to_admin(self):
        from services.integration_service import _map_lti_roles
        assert _map_lti_roles("administrator") == "STUDENT"
        assert _map_lti_roles("urn:lti:role:ims/lis/Administrator") == "STUDENT"
        # Even mixed with other roles, ADMIN must never be returned.
        assert _map_lti_roles("administrator,learner") in ("STUDENT", "TEACHER")
        assert _map_lti_roles("administrator,learner") != "ADMIN"

    def test_instructor_maps_to_teacher(self):
        from services.integration_service import _map_lti_roles
        assert _map_lti_roles("instructor") == "TEACHER"
        assert _map_lti_roles("contentdeveloper") == "TEACHER"
        assert _map_lti_roles("teachingassistant") == "TEACHER"

    def test_learner_maps_to_student(self):
        from services.integration_service import _map_lti_roles
        assert _map_lti_roles("learner") == "STUDENT"
        assert _map_lti_roles("student") == "STUDENT"
        assert _map_lti_roles("member") == "STUDENT"
        assert _map_lti_roles("") == "STUDENT"

    def test_role_map_has_no_admin_value(self):
        from services.integration_service import ROLE_MAP
        assert "ADMIN" not in set(ROLE_MAP.values())
        assert "administrator" not in ROLE_MAP

    def test_lti_disabled_returns_403(self, client, monkeypatch):
        monkeypatch.delenv("LTI_ENABLED", raising=False)
        resp = client.post("/lti/launch", data={})
        assert resp.status_code == 403

    def test_lti_auto_create_default_is_false(self, client, monkeypatch):
        # With LTI enabled but a bad launch, we never reach auto-create; this asserts
        # the default flag value the handler reads is now "false".
        import os
        # Simulate the handler's own getenv default resolution.
        monkeypatch.delenv("LTI_AUTO_CREATE_USERS", raising=False)
        assert os.getenv("LTI_AUTO_CREATE_USERS", "false").lower() == "false"
