"""SEC-SCOPE-9 — cross-teacher IDOR regression suite for the AI content READS in
``routes_ai.py``.

Context
=======
SEC-SCOPE-8 closed the course/chapter/content/question CRUD in ``main.py``. Its
adversarial QA gate found the SAME class of IDOR still open in ``routes_ai.py``:
a TEACHER/INSTRUCTOR could pass ANOTHER teacher's ``content_id`` in the request
body and receive AI output generated from the foreign material (question
generation, chapter suggestion, TTS, async audio, and content reprocessing — the
last of which also OVERWRITES the victim's content).

SEC-SCOPE-9 gates all 5 sites by REUSING the existing helpers from ``authz.py``
(``enforce_teacher_scope_on_read`` + ``assert_teacher_owns_content``) — no new
ownership logic. The gate is teacher-only by design:

  * TEACHER/INSTRUCTOR out of scope  -> 403/404, never the AI output.
  * ADMIN                            -> unrestricted (platform authority).
  * STUDENT                          -> untouched: the Socratic tutor carve-out
    (``POST /socrates/dialogue``, SEC-SCOPE-3) and student-reachable TTS paths
    must NOT be broken by this fix.

Ownership chain (on top of the conftest base seed)
==================================================
* ``DISCIPLINE_ID`` (conftest) is owned by ``TEACHER_ID`` (Teacher A).
* Teacher A's tree: COURSE_A -> CHAPTER_A -> CONTENT_A.
* A second teacher, ``TEACHER_B_ID``, owns a separate discipline and pokes at
  Teacher A's ``CONTENT_A`` across all 5 AI sites.

Harness: the shared in-memory ``fake_supabase`` from ``conftest.py`` (never edited
here). ElevenLabs/OpenAI are stubbed so the TTS/audio/reprocess paths never touch
the network — a denied request is proven to 403/404 BEFORE any AI call anyway.
"""
from __future__ import annotations

import sys
import threading as _threading
import types

import pytest

import routes_ai
from conftest import DISCIPLINE_ID, TEACHER_ID, _user

# ── Teacher B (the cross actor) + his own discipline ────────────────────────
TEACHER_B_ID = "teacher-b9"
DISCIPLINE_B_ID = "discipline-b9"

# ── Teacher A's content tree (rooted at conftest DISCIPLINE_ID) ─────────────
COURSE_A = "course-a9"
CHAPTER_A = "chapter-a9"
CONTENT_A = "content-a9"


def _seed_tree(fake):
    """Seed Teacher A's owned content tree + Teacher B's separate discipline."""
    fake.add("users", _user(TEACHER_B_ID, "TEACHER", "Teacher B9"))
    fake.add("disciplines", {"id": DISCIPLINE_B_ID, "title": "Teacher B9 Discipline"})
    fake.add("discipline_teachers", {"discipline_id": DISCIPLINE_B_ID, "teacher_id": TEACHER_B_ID})

    fake.add("courses", {"id": COURSE_A, "title": "Curso A9", "discipline_id": DISCIPLINE_ID,
                         "status": "active"})
    fake.add("chapters", {"id": CHAPTER_A, "course_id": COURSE_A, "title": "Cap A9", "order": 1})
    fake.add("contents", {"id": CONTENT_A, "chapter_id": CHAPTER_A, "title": "Cont A9",
                          "content_type": "text", "order": 1,
                          "body": "Material secreto do professor A."})
    fake.seed("tts_jobs", [])
    fake.seed("token_usage", [])


@pytest.fixture
def as_teacher_b(app):
    """Authenticate as Teacher B — the canonical cross-teacher actor."""
    from auth import get_current_user
    user = _user(TEACHER_B_ID, "TEACHER", "Teacher B9")
    app.dependency_overrides[get_current_user] = lambda: dict(user)
    return user


@pytest.fixture
def stub_ai(monkeypatch, fake_supabase):
    """Stub ElevenLabs/OpenAI + run TTS jobs inline so the AI paths are headless.

    A denied request never reaches these (the gate fires first), but stubbing
    guarantees an ACCIDENTAL leak would surface as real (fake) output rather than
    a 503 masking the bug.
    """
    from fakes import FakeAsyncOpenAI, FakeSyncOpenAI
    from services.ai_service import AIService

    monkeypatch.setattr(routes_ai, "ELEVENLABS_API_KEY", "fake-key", raising=False)
    svc = AIService(client=FakeAsyncOpenAI(response_text='{"questions": []}'),
                    sync_client=FakeSyncOpenAI(response_text="Resumo."))
    monkeypatch.setattr(routes_ai, "get_ai_service", lambda: svc)

    class _FakeTTS:
        def convert(self, **kwargs):
            yield b"FAKE"

    class _FakeElevenLabs:
        def __init__(self, api_key=None):
            self.text_to_speech = _FakeTTS()

    el_mod = types.ModuleType("elevenlabs.client")
    el_mod.ElevenLabs = _FakeElevenLabs
    monkeypatch.setitem(sys.modules, "elevenlabs.client", el_mod)

    supabase_mod = sys.modules.get("supabase") or types.ModuleType("supabase")
    monkeypatch.setattr(supabase_mod, "create_client", lambda url, key: fake_supabase, raising=False)
    monkeypatch.setitem(sys.modules, "supabase", supabase_mod)

    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._t, self._a, self._k = target, args, kwargs or {}

        def start(self):
            if self._t:
                self._t(*self._a, **self._k)

        def join(self, timeout=None):
            return None

        def is_alive(self):
            return False

    monkeypatch.setattr(_threading, "Thread", _SyncThread)
    return svc


# The 5 sites, each keyed to the field carrying content_id + a denied-leak assertion.
# (method, path, payload_builder)
_SITES = [
    ("POST", "/api/ai/creator/generate",
     lambda cid: {"content_id": cid}),
    ("POST", "/api/ai/creator/suggest-chapters",
     lambda cid: {"content_id": cid}),
    ("POST", "/api/ai/tts/generate",
     lambda cid: {"content_id": cid}),
    ("POST", "/api/ai/audio/generate-from-content",
     lambda cid: {"content_id": cid, "audio_type": "summary"}),
    ("POST", "/api/ai/reprocess-content",
     lambda cid: {"content_id": cid}),
]


# ===========================================================================
# (AC5) Cross-teacher B is blocked on ALL 5 AI content sites — no leak, no mutation.
# ===========================================================================
class TestCrossTeacherBlockedOnAllSites:
    @pytest.mark.parametrize("method,path,payload", _SITES)
    def test_cross_teacher_forbidden_no_content_leak(
        self, client, as_teacher_b, fake_supabase, stub_ai, method, path, payload
    ):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()

        resp = client.request(method, path, json=payload(CONTENT_A))

        assert resp.status_code in (403, 404), (
            f"{path}: cross teacher must be denied, got {resp.status_code}: {resp.text}"
        )
        # The victim's material must never echo back in the response body.
        assert "secreto" not in resp.text.lower(), (
            f"{path}: leaked Teacher A's content body to Teacher B"
        )
        # reprocess-content OVERWRITES content.body — prove it was NOT mutated.
        victim = fake_supabase.find("contents", id=CONTENT_A)
        assert victim is not None and victim["body"] == "Material secreto do professor A.", (
            f"{path}: cross teacher mutated Teacher A's content body"
        )


# ===========================================================================
# (AC1/floor) The owning teacher still reaches every site — the gate does not
# lock legitimate owners out.
# ===========================================================================
class TestOwningTeacherPasses:
    @pytest.mark.parametrize("method,path,payload", _SITES)
    def test_owner_not_blocked_by_authz(
        self, client, as_teacher, fake_supabase, stub_ai, method, path, payload
    ):
        _seed_tree(fake_supabase)
        resp = client.request(method, path, json=payload(CONTENT_A))
        # Downstream the (fake) AI may 200/2xx; it must NEVER be an authz block.
        assert resp.status_code not in (401, 403), (
            f"{path}: owning teacher wrongly blocked ({resp.status_code}): {resp.text}"
        )


# ===========================================================================
# (AC2) ADMIN keeps unrestricted access to every site.
# ===========================================================================
class TestAdminUnrestricted:
    @pytest.mark.parametrize("method,path,payload", _SITES)
    def test_admin_not_blocked_by_authz(
        self, client, as_admin, fake_supabase, stub_ai, method, path, payload
    ):
        _seed_tree(fake_supabase)
        resp = client.request(method, path, json=payload(CONTENT_A))
        assert resp.status_code not in (401, 403), (
            f"{path}: ADMIN wrongly blocked ({resp.status_code}): {resp.text}"
        )


# ===========================================================================
# (AC4) STUDENT carve-out is intact: the student-reachable AI paths are NOT
# gated by teacher-ownership. tts/generate + audio/generate-from-content are
# get_current_user; the tutor stays fully open.
# ===========================================================================
class TestStudentCarveOutIntact:
    def test_socrates_dialogue_still_open_to_student(self, client, as_student, stub_ai):
        resp = client.post(
            "/api/ai/socrates/dialogue",
            json={
                "student_message": "Tenho uma duvida",
                "chapter_content": "texto do capitulo",
                "initial_question": {"q": "?"},
            },
        )
        assert resp.status_code not in (401, 403), (
            f"socrates tutor must stay open to STUDENT, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.parametrize("path,payload", [
        ("/api/ai/tts/generate", {"content_id": CONTENT_A}),
        ("/api/ai/audio/generate-from-content", {"content_id": CONTENT_A, "audio_type": "summary"}),
    ])
    def test_student_not_blocked_by_teacher_scope_on_shared_tts(
        self, client, as_student, fake_supabase, stub_ai, path, payload
    ):
        # enforce_teacher_scope_on_read is a NO-OP for STUDENT (scoped by enrollment,
        # not teacher-ownership), so the SEC-SCOPE-9 gate must NOT 403 a student on
        # these get_current_user endpoints. (A student was never a teacher actor.)
        _seed_tree(fake_supabase)
        resp = client.post(path, json=payload)
        assert resp.status_code != 403, (
            f"{path}: SEC-SCOPE-9 teacher gate wrongly blocked a STUDENT "
            f"({resp.status_code}): {resp.text}"
        )
