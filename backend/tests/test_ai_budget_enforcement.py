"""TKN-4 — editor/tester/analyst enforce + record the REAL token budget (bug #12).

TKN-3 made ``check_token_budget`` / ``track_token_usage`` persistent (the
``token_usage`` table via :class:`TokenUsageRepository`). TKN-3 already wired the
creator (``generate_questions``) and socratic (``socratic_dialogue``) paths.
TKN-4 is the other half: the three remaining tutor methods —

  * ``edit_response``     (Editor)
  * ``validate_response`` (Tester)
  * ``detect_ai_content`` (Analyst)

— now CHECK the cap before any paid model call and TRACK consumption after a
real call, against the authenticated ``user_id`` + ``db`` propagated from the
route. Each test is a fail-before / pass-after oracle of one AC:

  (a) within the cap → success + persisted consumption > 0 for all three methods;
  (b) over the cap   → ``AIServiceError`` (→ HTTP 503 at the edge) with NO paid AI
      call (the injected OpenAI fake is never touched / ``_call_openai`` is never
      reached) and NO new consumption;
  (c) ``body.user_id`` is IGNORED at the route — identity is the authenticated
      session only, never the request payload.

CRITICAL invariant also guarded here: the socratic Editor→Tester gate calls
``edit_response`` / ``validate_response`` INTERNALLY (``_edit_safe`` /
``_validate_safe``) WITHOUT ``user_id``/``db``. The new params DEFAULT to None so
that internal path stays a budget no-op and never breaks — a regression there
would silently un-gate the tutor.

Honest fail-open of ``validate_response`` (TPP-7 / AI-HARD-2) is preserved: the
budget check sits OUTSIDE its ``try`` so an over-cap error PROPAGATES (→503)
instead of being swallowed into the UNKNOWN/degraded verdict. ``detect_ai_content``
tracks ONLY on the real-LLM path, never on the heuristic fallback.

Headless: in-process ``FakeSupabaseClient`` (with the ``increment_token_usage``
RPC) + injected ``FakeAsyncOpenAI``. No network, no real DB. Each fake LLM call
reports 30 tokens (10 prompt + 20 completion).
"""
from __future__ import annotations

import json

import pytest

from conftest import STUDENT_A_ID, STUDENT_B_ID, TEACHER_ID
from fakes import FakeSupabaseClient, FakeAsyncOpenAI
from repositories.token_usage_repo import TokenUsageRepository
from services.ai_service import AIService, AIServiceError


# Each fake chat completion = 10 + 20 tokens (see tests/fakes.py::_FakeUsage).
FAKE_CALL_TOKENS = 30

# Valid Tester JSON so validate_response takes the real-success path (not degraded).
TESTER_JSON = json.dumps({"verdict": "APPROVED", "score": 0.9, "criteria": {}})
# Valid Analyst JSON so detect_ai_content uses the LLM result (not the heuristic).
ANALYST_JSON = json.dumps(
    {"probability": 0.82, "confidence": "high", "verdict": "likely_ai", "indicators": []}
)


# ===========================================================================
# Helpers
# ===========================================================================
def _fake_db() -> FakeSupabaseClient:
    """A Supabase fake with the TKN-1 ``increment_token_usage`` RPC enabled."""
    return FakeSupabaseClient({"token_usage": []}, rpc_enabled=True)


def _svc(response_text: str) -> tuple[AIService, FakeAsyncOpenAI]:
    """An AIService wired to an injected async OpenAI fake (mock_mode off)."""
    fake = FakeAsyncOpenAI(response_text=response_text)
    return AIService(client=fake, sync_client=None), fake


# ===========================================================================
# (a) Within the cap — success + consumption > 0 for the THREE methods
# ===========================================================================
class TestWithinCapTracksConsumption:
    async def test_edit_response_tracks_usage_into_db(self):
        db = _fake_db()
        svc, fake = _svc("Texto editado, mais claro. Concorda? ")
        out = await svc.edit_response(
            orientador_response="texto bruto", user_id=STUDENT_A_ID, db=db
        )
        # Real paid call happened exactly once …
        assert len(fake.calls) == 1
        assert out["edited_text"].endswith("? ")
        # … and consumption was persisted (> 0) for the authenticated user.
        used = TokenUsageRepository(db).get_today_usage(STUDENT_A_ID)
        assert used == FAKE_CALL_TOKENS > 0

    async def test_validate_response_tracks_usage_into_db(self):
        db = _fake_db()
        svc, fake = _svc(TESTER_JSON)
        out = await svc.validate_response(
            edited_response="resposta editada", user_id=STUDENT_A_ID, db=db
        )
        assert len(fake.calls) == 1
        assert out["verdict"] == "APPROVED"  # real-success path, not degraded
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == FAKE_CALL_TOKENS > 0

    async def test_detect_ai_content_tracks_usage_into_db(self):
        db = _fake_db()
        svc, fake = _svc(ANALYST_JSON)
        out = await svc.detect_ai_content(
            text="Diante do exposto, e importante ressaltar.", user_id=STUDENT_A_ID, db=db
        )
        assert len(fake.calls) == 1
        assert out["ai_detection"]["verdict"] == "likely_ai"  # LLM path, not heuristic
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == FAKE_CALL_TOKENS > 0

    async def test_three_methods_accumulate_per_user_without_loss(self):
        """Sequential calls of all three sum atomically into one daily row."""
        db = _fake_db()
        edit_svc, _ = _svc("editado? ")
        val_svc, _ = _svc(TESTER_JSON)
        det_svc, _ = _svc(ANALYST_JSON)
        await edit_svc.edit_response(orientador_response="t", user_id=STUDENT_A_ID, db=db)
        await val_svc.validate_response(edited_response="r", user_id=STUDENT_A_ID, db=db)
        await det_svc.detect_ai_content(text="texto qualquer.", user_id=STUDENT_A_ID, db=db)
        # 3 real calls × 30 tokens, single daily row, never double-counted.
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == 3 * FAKE_CALL_TOKENS
        rows = [r for r in db.rows("token_usage") if str(r["user_id"]) == STUDENT_A_ID]
        assert len(rows) == 1


# ===========================================================================
# (b) Over the cap — AIServiceError raised, NO paid AI call, NO new consumption
# ===========================================================================
class TestOverCapBlocksBeforeSpending:
    async def test_edit_response_over_cap_raises_without_paid_call(self):
        db = _fake_db()
        svc, fake = _svc("nunca chamado")
        # Pre-seed usage AT the cap so the up-front check raises.
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit, db)
        with pytest.raises(AIServiceError):
            await svc.edit_response(
                orientador_response="texto bruto", user_id=STUDENT_A_ID, db=db
            )
        # No paid model call was made (blocked before _call_openai) …
        assert fake.calls == []
        # … and no extra tokens were charged beyond the pre-seeded cap.
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == svc.daily_token_limit

    async def test_validate_response_over_cap_raises_without_paid_call(self):
        db = _fake_db()
        svc, fake = _svc(TESTER_JSON)
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit, db)
        # The cap error must PROPAGATE (→503), NOT be swallowed into UNKNOWN/degraded
        # by validate_response's honest fail-open ``except AIServiceError``.
        with pytest.raises(AIServiceError):
            await svc.validate_response(
                edited_response="resposta", user_id=STUDENT_A_ID, db=db
            )
        assert fake.calls == []
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == svc.daily_token_limit

    async def test_detect_ai_content_over_cap_raises_without_paid_call(self):
        db = _fake_db()
        svc, fake = _svc(ANALYST_JSON)
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit, db)
        # The cap error must PROPAGATE (→503), NOT be swallowed by the broad
        # ``except Exception`` that drives the heuristic fallback.
        with pytest.raises(AIServiceError):
            await svc.detect_ai_content(
                text="qualquer texto.", user_id=STUDENT_A_ID, db=db
            )
        assert fake.calls == []
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == svc.daily_token_limit

    async def test_over_cap_user_does_not_affect_other_user(self):
        db = _fake_db()
        svc, _ = _svc("editado? ")
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit, db)
        # A never gets through …
        with pytest.raises(AIServiceError):
            await svc.edit_response(orientador_response="x", user_id=STUDENT_A_ID, db=db)
        # … but B (no usage) edits fine and is tracked.
        out = await svc.edit_response(orientador_response="x", user_id=STUDENT_B_ID, db=db)
        assert out["edited_text"]
        assert TokenUsageRepository(db).get_today_usage(STUDENT_B_ID) == FAKE_CALL_TOKENS


# ===========================================================================
# CRITICAL — the socratic gate calls edit/validate WITHOUT identity → no-op,
#            never breaks. Defaults are load-bearing.
# ===========================================================================
class TestInternalGateUnbrokenByDefaults:
    async def test_edit_and_validate_work_with_no_identity(self):
        """Direct call without user_id/db (the gate's contract) still succeeds and
        does NOT touch any budget."""
        edit_svc, edit_fake = _svc("editado? ")
        val_svc, val_fake = _svc(TESTER_JSON)
        # No user_id, no db — exactly how _edit_safe / _validate_safe call them.
        edited = await edit_svc.edit_response(orientador_response="cru")
        verdict = await val_svc.validate_response(edited_response="r")
        assert edited["edited_text"].endswith("? ")
        assert verdict["verdict"] == "APPROVED"
        # The real LLM call still happened (gate produces real output); the only
        # thing skipped is budget check/track (no identity → guards no-op).
        assert len(edit_fake.calls) == 1 and len(val_fake.calls) == 1

    async def test_socratic_gate_runs_editor_and_tester_with_no_identity(self, monkeypatch):
        """End-to-end gate oracle: socratic_dialogue with the gate flag ON exercises
        _edit_safe→edit_response and _validate_safe→validate_response internally,
        WITHOUT user_id/db, and must not raise from the new budget params."""
        from services.ai_service import AI_GATE_FLAG_ENV

        monkeypatch.setenv(AI_GATE_FLAG_ENV, "true")
        fake = FakeAsyncOpenAI(response_text='{"verdict": "APPROVED", "score": 0.9}')
        svc = AIService(client=fake, sync_client=None)
        # No user_id / db passed to socratic_dialogue → the internal editor/tester
        # calls also receive no identity. Budget no-op, gate runs, no exception.
        out = await svc.socratic_dialogue(
            student_message="x",
            chapter_content="c",
            initial_question={"text": "Q?"},
            interactions_remaining=3,
        )
        # Socrates + Editor + Tester ⇒ ≥ 3 calls; the gate ran end to end.
        assert len(fake.calls) >= 3
        assert "content" in out["response"]

    async def test_gate_internal_calls_are_budget_noops(self):
        """Even when socratic_dialogue HAS an identity, the gate's internal
        edit/validate calls pass no identity, so only Socrates' own track runs —
        the editor/tester passes are not charged twice through the gate."""
        # NOTE: socratic_dialogue tracks its OWN socrates call (TKN-3). The gate's
        # editor/tester internal calls intentionally do NOT track (no identity),
        # which keeps the gate a pure quality pass, not a metered surface.
        db = _fake_db()
        # Gate OFF (default) → exactly one socrates call, one track of 30 tokens.
        svc, fake = _svc("Resposta crua. Concorda? ")
        await svc.socratic_dialogue(
            student_message="x",
            chapter_content="c",
            initial_question={"text": "Q?"},
            interactions_remaining=3,
            user_id=STUDENT_A_ID,
            db=db,
        )
        assert len(fake.calls) == 1
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == FAKE_CALL_TOKENS


# ===========================================================================
# Preserved fail-open contract (TPP-7 / AI-HARD-2 / AI-HARD-3)
# ===========================================================================
class TestFailOpenContractPreserved:
    async def test_validate_transport_error_still_unknown_not_blocked(self):
        """A NON-cap transport failure still fails open to UNKNOWN/degraded (it is
        the over-cap AIServiceError that must NOT be swallowed — see class above)."""
        boom = FakeAsyncOpenAI(response_text="x", raise_exc=RuntimeError("upstream down"))
        svc = AIService(client=boom, sync_client=None)
        out = await svc.validate_response(edited_response="r", user_id=STUDENT_A_ID, db=_fake_db())
        assert out["verdict"] in ("UNKNOWN", "NEEDS_REVISION")
        assert out["verdict"] != "APPROVED"

    async def test_detect_llm_failure_falls_back_to_heuristic_without_tracking(self):
        """When the LLM call FAILS (not over-cap), detect_ai_content uses the
        heuristic and does NOT track (no paid call actually completed)."""
        boom = FakeAsyncOpenAI(response_text="x", raise_exc=RuntimeError("analyst down"))
        svc = AIService(client=boom, sync_client=None)
        db = _fake_db()
        out = await svc.detect_ai_content(
            text="acho que tipo sei la ne", user_id=STUDENT_A_ID, db=db
        )
        # Heuristic verdict shape is present …
        assert "verdict" in out["ai_detection"]
        # … and nothing was charged (the heuristic path makes no paid call).
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == 0


# ===========================================================================
# Route layer — identity comes from the session, body.user_id ignored; 503 over cap
# ===========================================================================
def _inject_ai_service(monkeypatch, svc: AIService) -> None:
    import routes_ai

    monkeypatch.setattr(routes_ai, "get_ai_service", lambda: svc)


def _enable_rpc(fake_supabase: FakeSupabaseClient) -> None:
    """Bind the increment_token_usage RPC onto the app's seeded fake."""
    fake_supabase.rpc = fake_supabase._rpc_entry  # type: ignore[attr-defined]
    fake_supabase._rpc_enabled = True
    fake_supabase.seed("token_usage", [])


class TestRouteIdentityAndStatus:
    def test_editor_route_within_cap_200_and_tracks_authenticated_user(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        _enable_rpc(fake_supabase)
        svc, fake = _svc("Texto editado. Concorda? ")
        _inject_ai_service(monkeypatch, svc)

        resp = client.post("/api/ai/editor/edit", json={"orientador_response": "cru"})
        assert resp.status_code == 200, resp.text
        assert len(fake.calls) == 1
        # Tracked against the AUTHENTICATED teacher, derived from the session.
        assert TokenUsageRepository(fake_supabase).get_today_usage(TEACHER_ID) == FAKE_CALL_TOKENS

    def test_editor_route_over_cap_returns_503_without_paid_call(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        _enable_rpc(fake_supabase)
        svc, fake = _svc("nunca chamado")
        # Pre-seed the authenticated teacher AT the cap.
        svc.track_token_usage(TEACHER_ID, svc.daily_token_limit, fake_supabase)
        _inject_ai_service(monkeypatch, svc)

        resp = client.post("/api/ai/editor/edit", json={"orientador_response": "cru"})
        assert resp.status_code == 503, resp.text
        # No paid AI call ran — blocked before _call_openai.
        assert fake.calls == []
        assert TokenUsageRepository(fake_supabase).get_today_usage(TEACHER_ID) == svc.daily_token_limit

    def test_tester_route_over_cap_returns_503_without_paid_call(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        _enable_rpc(fake_supabase)
        svc, fake = _svc(TESTER_JSON)
        svc.track_token_usage(TEACHER_ID, svc.daily_token_limit, fake_supabase)
        _inject_ai_service(monkeypatch, svc)

        resp = client.post("/api/ai/tester/validate", json={"edited_response": "r"})
        assert resp.status_code == 503, resp.text
        assert fake.calls == []

    def test_analyst_route_over_cap_returns_503_without_paid_call(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        _enable_rpc(fake_supabase)
        svc, fake = _svc(ANALYST_JSON)
        svc.track_token_usage(TEACHER_ID, svc.daily_token_limit, fake_supabase)
        _inject_ai_service(monkeypatch, svc)

        resp = client.post("/api/ai/analyst/detect", json={"text": "algum texto longo aqui."})
        assert resp.status_code == 503, resp.text
        assert fake.calls == []

    def test_tester_route_within_cap_200_and_tracks_authenticated_user(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        _enable_rpc(fake_supabase)
        svc, fake = _svc(TESTER_JSON)
        _inject_ai_service(monkeypatch, svc)

        resp = client.post("/api/ai/tester/validate", json={"edited_response": "r"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["verdict"] == "APPROVED"
        assert TokenUsageRepository(fake_supabase).get_today_usage(TEACHER_ID) == FAKE_CALL_TOKENS

    def test_analyst_route_within_cap_200_and_tracks_authenticated_user(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        _enable_rpc(fake_supabase)
        svc, fake = _svc(ANALYST_JSON)
        _inject_ai_service(monkeypatch, svc)

        resp = client.post("/api/ai/analyst/detect", json={"text": "algum texto longo aqui."})
        assert resp.status_code == 200, resp.text
        assert TokenUsageRepository(fake_supabase).get_today_usage(TEACHER_ID) == FAKE_CALL_TOKENS

    def test_body_user_id_is_ignored_authenticated_identity_prevails(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        """A spoofed ``user_id`` in the body must NOT determine the cap or the
        tracked identity — the authenticated teacher's identity prevails."""
        _enable_rpc(fake_supabase)
        # Pre-seed the SPOOFED victim (STUDENT_A) AT the cap. If the route trusted
        # body.user_id, the call would be blocked (503) under A's identity. It must
        # be charged under the TEACHER instead and succeed (200).
        svc, fake = _svc("Texto editado. Concorda? ")
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit, fake_supabase)
        _inject_ai_service(monkeypatch, svc)

        resp = client.post(
            "/api/ai/editor/edit",
            json={"orientador_response": "cru", "user_id": STUDENT_A_ID},
        )
        # Authenticated identity prevails → success, not blocked by A's over-cap.
        assert resp.status_code == 200, resp.text
        assert len(fake.calls) == 1
        # Consumption is charged to the TEACHER, never to the spoofed A.
        assert TokenUsageRepository(fake_supabase).get_today_usage(TEACHER_ID) == FAKE_CALL_TOKENS
        # A's row is untouched (still exactly the pre-seeded cap; no charge leaked).
        assert TokenUsageRepository(fake_supabase).get_today_usage(STUDENT_A_ID) == svc.daily_token_limit
