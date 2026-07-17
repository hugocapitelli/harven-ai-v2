"""Routes — AI, Chat Sessions, Integrations, LTI, Uploads."""
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from supabase import Client

from auth import create_access_token, get_current_user, require_role
from authz import assert_owner_or_role, load_session_or_404, require_self_or_role
from config import get_settings
from database import get_supabase
from repositories.chat_repo import ChatRepository
from schemas.ai import AIDetectionResponse
from schemas.chat import ChatSessionCreate
from services.ai_service import AIService, AIServiceError, sanitize_ai_error
from services.scoring import compute_performance_score
from services.integration_service import (
    IntegrationService,
    LTIValidationError,
    generate_lti_config_xml,
    validate_lti_launch,
    verify_moodle_webhook_signature,
)
from services.storage_service import StorageService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ElevenLabs TTS
# ---------------------------------------------------------------------------

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

router = APIRouter()

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_ai_service: Optional[AIService] = None
_storage_service: Optional[StorageService] = None


def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service


def get_storage_service() -> StorageService:
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service


def get_integration_service(client: Client = Depends(get_supabase)) -> IntegrationService:
    settings = get_settings()
    return IntegrationService(client, {
        "jacad_base_url": os.getenv("JACAD_BASE_URL", ""),
        "jacad_api_key": os.getenv("JACAD_API_KEY", ""),
        "moodle_url": os.getenv("MOODLE_URL", ""),
        "moodle_token": os.getenv("MOODLE_TOKEN", ""),
    })


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class QuestionGenerationRequest(BaseModel):
    content_id: Optional[str] = None
    chapter_content: str = Field("", max_length=50000)
    chapter_title: Optional[str] = Field("", max_length=300)
    learning_objective: Optional[str] = Field("", max_length=1000)
    difficulty: Optional[str] = Field("intermediario", max_length=30)
    max_questions: Optional[int] = Field(5, ge=1, le=20)


class InitialQuestion(BaseModel):
    """Typed contract for the socratic seed question (TPP-4, bug #41).

    ``text`` is REQUIRED: an empty/missing question now yields a 422 validation
    error instead of a silently degraded prompt ("Pergunta em discussao:" blank).
    ``expected_answer`` stays optional (a friendly default is used when absent).
    """
    text: str = Field(..., min_length=1, max_length=5000)
    expected_answer: Optional[str] = Field(None, max_length=5000)


class SocraticDialogueRequest(BaseModel):
    student_message: str = Field(..., min_length=1, max_length=5000)
    chapter_content: str = Field(..., max_length=50000)
    initial_question: InitialQuestion
    conversation_history: Optional[List[dict]] = []
    # TPP-5: pacing is DERIVED server-side from the persisted message count when a
    # ``session_id`` is present. This field is retained only for contract
    # backwards-compat (older clients still send it); it is NOT trusted to drive
    # ``should_finalize`` / ``interactions_remaining`` once a session exists.
    interactions_remaining: Optional[int] = Field(3, ge=0, le=20)
    session_id: Optional[str] = None
    chapter_id: Optional[str] = None
    # GRD-4: the opening trigger ("Quero explorar a questão ...") is NOT a student
    # turn. When true the backend generates the first question WITHOUT counting it
    # against the student's interaction limit (kickoff never consumes limit). Older
    # clients omit it → defaults to False (a real turn, unchanged behavior).
    is_kickoff: bool = False


class AIDetectionRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    context: Optional[dict] = None
    interaction_metadata: Optional[dict] = None


class EditResponseRequest(BaseModel):
    orientador_response: str
    context: Optional[dict] = None


class ValidateResponseRequest(BaseModel):
    edited_response: str
    context: Optional[dict] = None


class OrganizeSessionRequest(BaseModel):
    action: str
    payload: dict
    metadata: Optional[dict] = None


# ChatSessionCreate is imported from schemas.chat (single source of truth, TPP-2):
# the previous duplicate definition here caused contract drift. ``user_id`` lives
# on that model only for backwards-compat and is never trusted for authorization.


class ChatMessageCreate(BaseModel):
    role: str = Field(..., max_length=20)
    content: str = Field(..., min_length=1, max_length=10000)
    agent_type: Optional[str] = Field(None, max_length=50)
    metadata: Optional[dict] = None


# ===================================================================
# AI ENDPOINTS
# ===================================================================


@router.get("/api/ai/status", tags=["AI"])
async def ai_status():
    svc = get_ai_service()
    return {
        "enabled": svc.enabled,
        "mock_mode": svc.mock_mode,
        "model": svc.model,
        "agents": svc.supported_agents(),
        "daily_token_limit": svc.daily_token_limit,
    }


@router.post("/api/ai/creator/generate", tags=["AI"])
async def ai_creator_generate(
    req: QuestionGenerationRequest,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    try:
        chapter_content = req.chapter_content or ""
        chapter_title = req.chapter_title or ""

        # If no content provided but content_id exists, load from DB
        if not chapter_content.strip() and req.content_id:
            from repositories import ContentRepository
            content_repo = ContentRepository(client)
            content_record = content_repo.get_by_id(req.content_id)
            if content_record:
                chapter_content = content_record.get("body") or ""
                chapter_title = chapter_title or content_record.get("title") or ""

        if not chapter_content.strip():
            raise HTTPException(status_code=400, detail="Sem conteudo para processar. Envie um documento com texto extraivel.")

        return await get_ai_service().generate_questions(
            chapter_content=chapter_content,
            chapter_title=chapter_title,
            learning_objective=req.learning_objective or "",
            difficulty=req.difficulty or "intermediario",
            max_questions=req.max_questions or 3,
            user_id=current_user["id"],
            db=client,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Creator error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro ao gerar questoes: {str(e)[:200]}")


@router.post("/api/ai/creator/suggest-chapters", tags=["AI"])
async def ai_suggest_chapters(
    req: QuestionGenerationRequest,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    """Analyze uploaded content and suggest chapter splits based on headings."""
    content_text = req.chapter_content or ""
    if not content_text.strip() and req.content_id:
        from repositories import ContentRepository
        content_repo = ContentRepository(client)
        content_record = content_repo.get_by_id(req.content_id)
        if content_record:
            content_text = content_record.get("body") or ""

    if not content_text.strip():
        return {"chapters": [], "message": "Sem conteudo para analisar"}

    from services.text_extractor import split_markdown_into_chapters
    chapters = split_markdown_into_chapters(content_text)
    return {
        "chapters": [
            {
                "title": c["title"],
                "preview": c["body"][:200] + "..." if len(c["body"]) > 200 else c["body"],
                "word_count": len(c["body"].split()),
            }
            for c in chapters
        ],
        "total_chapters": len(chapters),
        "total_words": len(content_text.split()),
    }


@router.post("/api/ai/socrates/dialogue", tags=["AI"])
async def ai_socrates_dialogue(
    req: SocraticDialogueRequest,
    # carve-out: tutor do aluno — NÃO gatear (SEC-SCOPE-3). STUDENT must reach this
    # endpoint (200); gating it by role would break the Socratic tutor for ALL
    # students. Keep get_current_user (any authenticated user), never require_role.
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    try:
        result = await get_ai_service().socratic_dialogue(
            student_message=req.student_message,
            chapter_content=req.chapter_content,
            # InitialQuestion (TPP-4) -> dict for the service's typed accessors.
            initial_question=req.initial_question.model_dump(),
            conversation_history=req.conversation_history,
            # TPP-5: still passed for the no-session fallback path, but ignored as a
            # source of truth when ``session_id`` resolves to a persisted transcript.
            interactions_remaining=req.interactions_remaining or 3,
            session_id=req.session_id,
            user_id=current_user["id"],
            db=client,
            is_kickoff=req.is_kickoff,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Socrates error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")

    # SOC-2 (zombie fix): when this turn is the 3rd (finalizing) one, mark the
    # session ``completed`` SERVER-SIDE so it never lingers as an exhausted ``active``
    # zombie that a later create-or-get resumes (consuming the kickoff as a real turn
    # and finalizing on the 1st message — the 0/3 screenshot). This reuses the SAME
    # completion authority as ``PUT .../complete`` (``_apply_session_completion``:
    # idempotent + GRD-2 guard + DATA-GAM-3 score), so there is no duplicate logic and
    # no double conclusion. It is BEST-EFFORT: a failure here is logged and must NEVER
    # derail the tutor reply the student is waiting on (house pattern for the additive
    # completion edge). Ownership is re-gated (the caller is the student who owns the
    # session; a spoofed session_id is caught before any write).
    if result.get("session_status", {}).get("should_finalize") and req.session_id:
        try:
            session = load_session_or_404(client, req.session_id)
            assert_owner_or_role(
                session.get("user_id"), current_user, "ADMIN", "TEACHER", "INSTRUCTOR"
            )
            await _apply_session_completion(client, session)
        except Exception as exc:  # pragma: no cover - additive edge, never blocking
            logger.warning(
                "ai_socrates_dialogue: server-side completion on finalize failed "
                "(session=%s): %s",
                req.session_id, exc,
            )

    return result


@router.post("/api/ai/analyst/detect", tags=["AI"], response_model=AIDetectionResponse)
async def ai_analyst_detect(
    req: AIDetectionRequest,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    try:
        # TKN-4 (bug #12): identity for the budget cap comes EXCLUSIVELY from the
        # authenticated session (``current_user["id"]``), never ``body.user_id``.
        return await get_ai_service().detect_ai_content(
            text=req.text,
            context=req.context,
            interaction_metadata=req.interaction_metadata,
            user_id=current_user["id"],
            db=client,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Analyst error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/editor/edit", tags=["AI"])
async def ai_editor_edit(
    req: EditResponseRequest,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    try:
        # TKN-4 (bug #12): authenticated identity only — never body.user_id.
        return await get_ai_service().edit_response(
            orientador_response=req.orientador_response,
            context=req.context,
            user_id=current_user["id"],
            db=client,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Editor error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/tester/validate", tags=["AI"])
async def ai_tester_validate(
    req: ValidateResponseRequest,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    try:
        # TKN-4 (bug #12): authenticated identity only — never body.user_id.
        return await get_ai_service().validate_response(
            edited_response=req.edited_response,
            context=req.context,
            user_id=current_user["id"],
            db=client,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Tester error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/organizer/session", tags=["AI"])
async def ai_organizer_session(
    req: OrganizeSessionRequest,
    # SEC-SCOPE-3: AI authoring/organizer is role-gated (STUDENT -> 403).
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    try:
        payload = dict(req.payload)

        # Enrich get_session_status with real DB data
        if req.action == "get_session_status":
            session_id = payload.get("session_id")
            if session_id:
                # SEC-CHAT-4: ownership gate BEFORE reading status/message counts.
                # Resolve the session from the DB and assert the caller owns it (or
                # is a privileged role). A cross-user/non-owner actor gets 403/404
                # and NO status nor total_messages is leaked. ``session_id`` from the
                # body is only used to *load* the row — never to authorize.
                session = load_session_or_404(client, session_id)
                assert_owner_or_role(
                    session.get("user_id"), current_user, "ADMIN", "TEACHER", "INSTRUCTOR"
                )

                payload["status"] = session.get("status", "active")

                # Count actual messages from chat_messages table
                msg_count_result = client.table("chat_messages").select(
                    "id", count="exact"
                ).eq("session_id", session_id).execute()
                actual_count = msg_count_result.count if msg_count_result and msg_count_result.count is not None else 0
                payload["total_messages"] = actual_count

        return await get_ai_service().organize_session(
            action=req.action,
            payload=payload,
            metadata=req.metadata,
        )
    except HTTPException:
        # Authorization decisions (403/404 from the ownership gate) must keep
        # their status code — never be masked as a 500 by the generic handler.
        raise
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Organizer error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/organizer/prepare-export", tags=["AI"])
async def ai_organizer_prepare_export(
    session_data: dict,
    # SEC-SCOPE-3: AI authoring/organizer is role-gated (STUDENT -> 403).
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    try:
        enriched = dict(session_data)

        # SEC-CHAT-1 / SEC-CHAT-4: ownership gate runs BEFORE any enrichment.
        # Resolve the session strictly by ``session_id`` (a path/body identity is
        # only used to LOAD the row, never to authorize), assert the caller owns it
        # (or holds a privileged role), and ONLY THEN load chat_messages + users
        # (PII: name/email). A non-owner gets 403/404 and zero queries against
        # chat_messages / users fire — no transcript, name or email can leak.
        session_id = enriched.get("session_id")
        session_row: Optional[dict] = None
        if session_id and not enriched.get("messages"):
            session_row = load_session_or_404(client, session_id)
            assert_owner_or_role(
                session_row.get("user_id"), current_user, "ADMIN", "TEACHER", "INSTRUCTOR"
            )

            for k, v in session_row.items():
                enriched.setdefault(k, v)
            enriched.setdefault("session_id", session_row.get("id"))

            msgs_result = client.table("chat_messages").select("*").eq(
                "session_id", session_id
            ).order("created_at").execute()
            enriched["messages"] = msgs_result.data or []

        # SEC-CHAT-4: the export actor (user_name/user_email) is derived strictly
        # from the OWNER of the loaded session (``session_row["user_id"]``), never
        # from a client-supplied ``body.user_id``. When no session was loaded (raw
        # payload export), fall back to the authenticated user — still never the body.
        if session_row is not None:
            actor_user_id = session_row.get("user_id")
        else:
            actor_user_id = current_user.get("id")
        # Drop any forged body.user_id so it cannot influence the actor downstream.
        enriched["user_id"] = actor_user_id

        user_id = actor_user_id
        if user_id and (not enriched.get("user_name") or not enriched.get("user_email")):
            user_result = client.table("users").select("name, email").eq(
                "id", user_id
            ).maybe_single().execute()
            if user_result and user_result.data:
                enriched.setdefault("user_name", user_result.data.get("name") or "")
                enriched.setdefault("user_email", user_result.data.get("email") or "")

        # Populate context: content -> chapter -> course
        content_id = enriched.get("content_id")
        if content_id and not enriched.get("course_title"):
            content_result = client.table("contents").select("id, title, chapter_id").eq(
                "id", content_id
            ).maybe_single().execute()
            if content_result and content_result.data:
                enriched.setdefault("content_title", content_result.data.get("title") or "")
                chapter_id = content_result.data.get("chapter_id") or enriched.get("chapter_id")
                if chapter_id:
                    enriched.setdefault("chapter_id", chapter_id)
                    chapter_result = client.table("chapters").select("id, title, course_id").eq(
                        "id", chapter_id
                    ).maybe_single().execute()
                    if chapter_result and chapter_result.data:
                        enriched.setdefault("chapter_title", chapter_result.data.get("title") or "")
                        course_id = chapter_result.data.get("course_id") or enriched.get("course_id")
                        if course_id:
                            enriched.setdefault("course_id", course_id)
                            course_result = client.table("courses").select("id, title").eq(
                                "id", course_id
                            ).maybe_single().execute()
                            if course_result and course_result.data:
                                enriched.setdefault("course_title", course_result.data.get("title") or "")

        # Fallbacks for required fields
        enriched.setdefault("user_name", "Unknown Student")
        enriched.setdefault("user_email", "unknown@harven.ai")
        enriched.setdefault("course_title", "Unknown Course")
        enriched.setdefault("chapter_title", "Unknown Chapter")
        enriched.setdefault("content_title", "Unknown Content")

        return get_ai_service().prepare_moodle_export(enriched)
    except HTTPException:
        # Ownership decisions (403/404) must surface unchanged — never as a 500.
        raise
    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.get("/api/ai/estimate-cost", tags=["AI"])
async def ai_estimate_cost(
    prompt_tokens: int = Query(0, ge=0),
    completion_tokens: int = Query(0, ge=0),
    model: str = Query(""),
    # SEC-SCOPE-3: estimate-cost previously had NO auth; now requires a role so it
    # no longer leaks pricing/model config to anonymous/STUDENT callers.
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
):
    svc = get_ai_service()
    return {
        "estimated_cost_usd": svc.estimate_cost(prompt_tokens, completion_tokens, model),
        "model": model or svc.model,
    }


# ===================================================================
# TTS ENDPOINTS (stubs — real implementation depends on provider)
# ===================================================================


ELEVENLABS_VOICES = {
    "21m00Tcm4TlvDq8ikWAM": {"name": "Rachel", "gender": "female"},
    "29vD33N1CtxCmqQRPOHJ": {"name": "Drew", "gender": "male"},
    "EXAVITQu4vr4xnSDxMaL": {"name": "Bella", "gender": "female"},
    "ErXwobaYiN019PkySvjV": {"name": "Antoni", "gender": "male"},
    "MF3mGyEYCl7XYWbV9V6O": {"name": "Elli", "gender": "female"},
    "TxGEqnHWrfWFTfGW9XjX": {"name": "Josh", "gender": "male"},
}


@router.get("/api/ai/tts/voices", tags=["AI - TTS"])
async def tts_voices():
    return {
        "voices": [
            {"id": vid, "name": meta["name"], "gender": meta["gender"]}
            for vid, meta in ELEVENLABS_VOICES.items()
        ]
    }


class TTSGenerateRequest(BaseModel):
    text: Optional[str] = Field(None, max_length=50000)
    voice: str = Field("21m00Tcm4TlvDq8ikWAM", max_length=50)
    content_id: Optional[str] = None


@router.post("/api/ai/tts/generate", tags=["AI - TTS"])
async def tts_generate(
    body: TTSGenerateRequest,
    current_user: dict = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    client: Client = Depends(get_supabase),
):
    if not ELEVENLABS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="TTS indisponivel: ELEVENLABS_API_KEY nao configurada.",
        )

    # Resolve text: from body.text or from content_id
    text = body.text or ""
    if not text.strip() and body.content_id:
        from repositories import ContentRepository
        content_repo = ContentRepository(client)
        content_record = content_repo.get_by_id(body.content_id)
        if content_record:
            text = content_record.get("body") or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="Texto vazio. Envie 'text' ou 'content_id' valido.")

    voice_id = body.voice if body.voice in ELEVENLABS_VOICES else "21m00Tcm4TlvDq8ikWAM"

    # ASYNC-AI-2: the ElevenLabs SDK has no stable async client, and the blocking
    # part is BOTH the network ``convert()`` AND draining the returned generator with
    # ``b"".join(...)`` (that drain is where bytes are streamed off the socket). Both
    # MUST run inside a single threadpool closure — joining outside the threadpool
    # would put the real network blocking right back on the event loop.
    def _synthesize() -> bytes:
        from elevenlabs.client import ElevenLabs
        el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        audio_generator = el_client.text_to_speech.convert(
            text=text[:5000],
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        return b"".join(audio_generator)

    try:
        audio_bytes = await run_in_threadpool(_synthesize)
    except Exception as e:
        logger.error(f"TTS generate failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Falha na chamada ElevenLabs TTS: {sanitize_ai_error(e)}")

    subdir = "tts"
    dest_dir = storage.base_dir / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.mp3"
    dest_path = dest_dir / filename

    try:
        with open(dest_path, "wb") as f:
            f.write(audio_bytes)
    except Exception as e:
        logger.error(f"TTS file write failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Falha ao salvar audio gerado.")

    audio_url = f"/uploads/{subdir}/{filename}"
    return {
        "status": "ok",
        "audio_url": audio_url,
        "voice": voice_id,
        "provider": "elevenlabs",
        "model": "eleven_multilingual_v2",
        "size_bytes": len(audio_bytes),
    }


class AudioGenerateRequest(BaseModel):
    content_id: str = Field(..., min_length=1)
    audio_type: str = Field("summary", pattern="^(podcast|summary|explanation)$")
    voice: str = Field("21m00Tcm4TlvDq8ikWAM", max_length=50)


# ---------------------------------------------------------------------------
# TTS job lifecycle — TTSJOB-2 (persisted, non-destructive, ownership-scoped).
# ---------------------------------------------------------------------------
# The job lifecycle is now persisted in the `tts_jobs` table (TTSJOB-1) instead
# of a process-local dict (bug #34/#58/#59/#60): jobs survive a backend restart,
# ``audio_job_status`` reads are non-destructive (no pop), ownership is enforced
# on every read (cross-user -> 404, never a leaked row), and terminal jobs are
# swept by TTL instead of accumulating forever.
#
# Concurrency knobs (POD-4, bug #35): a soft in-process lock plus a cap on
# active jobs per user. The lock is process-local (single-worker deploy, see
# CLAUDE.md deploy notes) — it prevents two near-simultaneous submits in THIS
# process from racing past the dedup check before either has written its
# `processing` row; it does not need to be distributed for that guarantee.
_TTS_DISPATCH_LOCK = None  # lazily created — see _dispatch_lock()

# Max wall-clock time a synthesis job may run before it is forced into `error`
# instead of being left in `processing` forever (POD-4 timeout requirement).
TTS_JOB_TIMEOUT_SECONDS = 600  # 10 minutes

# Max number of `processing` jobs a single user may have in flight at once.
TTS_MAX_ACTIVE_JOBS_PER_USER = 2

# TTL for terminal (`done`/`error`) jobs before they are swept from `tts_jobs`.
# Set far longer than the frontend's ~90s polling window, so a legitimate poll
# never races the sweep; a swept job_id simply 404s on `audio_job_status`
# (``contents.audio_url``/``audio_type`` — persisted independently on `done`,
# see ``_persist_audio_url_with_retry`` — remains the durable source of truth
# for the audio itself regardless of whether the job row still exists).
TTS_JOB_TTL = timedelta(hours=24)

# ElevenLabs' documented per-request character ceiling. Text longer than this is
# chunked (POD-2 chunk-and-concatenate) rather than silently truncated.
TTS_MAX_CHARS_PER_CALL = 4500


def _dispatch_lock():
    """Lazily create the process-local dispatch lock (import-time-safe)."""
    global _TTS_DISPATCH_LOCK
    if _TTS_DISPATCH_LOCK is None:
        import threading
        _TTS_DISPATCH_LOCK = threading.Lock()
    return _TTS_DISPATCH_LOCK


def _chunk_text_for_tts(text: str, max_chars: int = TTS_MAX_CHARS_PER_CALL) -> List[str]:
    """Split ``text`` into <= ``max_chars`` chunks, cutting on sentence/paragraph
    boundaries when possible so no chunk splits mid-word.

    Prefers ``services.ai_service.chunk_text`` (POD-1's shared helper) when it is
    available, so both TTS entry points converge on the SAME chunking logic and
    never drift. Falls back to a local, dependency-free splitter (below) when
    that helper has not landed yet or fails to import — this route module is
    never blocked on POD-1/POD-2 shipping first.
    """
    try:
        from services.ai_service import chunk_text as _shared_chunk_text  # type: ignore
        return _shared_chunk_text(text, max_chars)
    except ImportError:
        pass

    # Local fallback contract mirrors the shared helper's: empty/whitespace-only
    # input carries nothing to narrate -> no chunks (never a crash, never a
    # single spurious empty synthesis call).
    if not text or not text.strip():
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        # Prefer breaking on a paragraph, then sentence, then whitespace boundary
        # so words are never split mid-token.
        split_at = max(
            window.rfind("\n\n"),
            window.rfind(". "),
            window.rfind(" "),
        )
        if split_at <= 0:
            split_at = max_chars
        else:
            split_at += 1  # keep the boundary character with the completed chunk
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return [c for c in chunks if c] or [text[:max_chars]]


def _synthesize_mp3_chunks(el_client, chunks: List[str], voice_id: str) -> bytes:
    """Synthesize each chunk via ElevenLabs and concatenate the resulting MP3
    bytes in order into a single buffer.

    Any chunk failing to synthesize aborts the WHOLE job (raises) rather than
    persisting a partial/truncated MP3 (POD-2 AC: no silent partial audio).
    Binary concatenation of MP3 frames produced with the same encoder/model/
    output_format (as here — every chunk uses identical synthesis params) plays
    back as one continuous stream, matching POD-1's validated approach.
    """
    parts: List[bytes] = []
    for idx, chunk in enumerate(chunks):
        try:
            audio_generator = el_client.text_to_speech.convert(
                text=chunk,
                voice_id=voice_id,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            parts.append(b"".join(audio_generator))
        except Exception as exc:
            raise RuntimeError(
                f"Falha na sintese do trecho {idx + 1}/{len(chunks)}: {exc}"
            ) from exc
    return b"".join(parts)


def _persist_audio_url_with_retry(
    sb, content_id: str, audio_url: str, audio_type: str, attempts: int = 3
) -> bool:
    """Persist ``contents.audio_url``/``audio_type`` with retry; return whether it
    actually landed (POD-3/POD-4 bug #35 — no more silent 'done' on a failed
    UPDATE). Retries are synchronous/blocking — this already runs off the event
    loop (background thread) — with no sleep between attempts by default, which
    is sufficient for the transient-network-blip case this guards against
    without adding latency for the common (single-attempt-succeeds) path.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            res = (
                sb.table("contents")
                .update({"audio_url": audio_url, "audio_type": audio_type})
                .eq("id", content_id)
                .execute()
            )
            if getattr(res, "data", None):
                return True
            # Empty data with no exception: the row may not exist (deleted
            # content) — treat as a non-retryable failure, but still honest.
            last_exc = RuntimeError("UPDATE returned no rows")
        except Exception as exc:  # pragma: no cover - defensive, exercised via mocks
            last_exc = exc
            logger.warning(
                "persist_audio_url attempt %d/%d failed for content_id=%s: %s",
                attempt, attempts, content_id, exc,
            )
    logger.error(
        "persist_audio_url: all %d attempts FAILED for content_id=%s audio_url=%s: %s",
        attempts, content_id, audio_url, last_exc,
    )
    return False


def _run_tts_job(job_id: str, content_id: str, content_text: str, audio_type: str, voice_id: str, upload_dir: str, supabase_url: str, supabase_key: str, user_id: Optional[str] = None):
    """Background TTS generation — runs in a thread, persists lifecycle to `tts_jobs`.

    TKN-5 (bug #12): the two paid AI steps of this pipeline are billed to the
    INITIATOR's daily ledger via the unified TKN-3 tracker:

    * the LLM (script/summary/explanation) — ``result.usage.total_tokens``;
    * the ElevenLabs synthesis — a char-equivalent (``len(tts_input)``) summed into
      the SAME ``tokens_used`` counter, gated by ``ENABLE_ELEVENLABS_COST_TRACKING``
      (KISS: no provider column in the schema; the provider is disambiguated in the
      structured log rather than the ledger).

    TTSJOB-2 (bug #34/#58/#59/#60): the job's lifecycle row lives in `tts_jobs`
    (via ``TtsJobRepository``), not a process dict — every terminal transition
    below is a DB ``UPDATE``, so a restart never strands the poller and status
    reads never need to mutate/pop anything.

    POD-2/POD-3 (bug #8/#33/#34): the narration text is chunked (never truncated)
    and synthesized/concatenated as one MP3; the ``done`` status is only ever
    reached after the audio_url UPDATE actually lands — a persistence failure
    (even after retries) is surfaced as ``error``, never a silent phantom-done.

    The async event loop's ``get_supabase`` dependency does not exist inside this
    thread, so a SYNC Supabase ``Client`` is recreated here from the
    ``supabase_url``/``supabase_key`` already handed to the job and used both for
    ledger writes and for the ``tts_jobs``/``contents`` persistence below.
    """
    from repositories.tts_job_repo import TtsJobRepository
    from supabase import create_client

    db = None
    try:
        db = create_client(supabase_url, supabase_key)
    except Exception as exc:  # pragma: no cover - defensive: never block audio
        logger.error(
            "TTS job %s: failed to create Supabase client "
            "(user_id=%s, content_id=%s) — lifecycle/ledger will not be persisted: %s",
            job_id, user_id, content_id, exc,
        )

    job_repo = TtsJobRepository(db) if db is not None else None

    def _finish_error(message: str) -> None:
        logger.error("TTS job %s failed: %s", job_id, message)
        if job_repo is not None:
            try:
                job_repo.mark_error(job_id, message)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("TTS job %s: failed to persist error state: %s", job_id, exc)

    try:
        svc = get_ai_service()
        tts_input = content_text

        cfg = get_settings()

        # ASYNC-AI-1: this job runs in a threading.Thread (OFF the event loop).
        # ``svc.client`` is now ``AsyncOpenAI`` and MUST NOT be called here (calling a
        # coroutine synchronously would silently break summary/explanation audio).
        # Use the dedicated SYNCHRONOUS client (``svc.sync_client``) instead — this is
        # QA verification item #1 (no async/coroutine exception leaks into the thread).
        sync_client = svc.sync_client
        llm_result = None

        if audio_type == "summary" and sync_client:
            llm_result = sync_client.chat.completions.create(
                model=svc.model,
                messages=[
                    {"role": "system", "content": "Voce e um assistente educacional. Resuma o conteudo abaixo de forma clara e concisa, em portugues, mantendo os conceitos-chave. Maximo 3 paragrafos."},
                    {"role": "user", "content": content_text[:8000]},
                ],
                max_tokens=800,
            )
            tts_input = llm_result.choices[0].message.content or content_text
        elif audio_type == "explanation" and sync_client:
            llm_result = sync_client.chat.completions.create(
                model=svc.model,
                messages=[
                    {"role": "system", "content": "Voce e um professor didatico. Transforme o conteudo abaixo em uma explicacao clara e acessivel, como se estivesse explicando para um aluno. Use linguagem natural e exemplos quando possivel. Em portugues. Maximo 4 paragrafos."},
                    {"role": "user", "content": content_text[:8000]},
                ],
                max_tokens=1000,
            )
            tts_input = llm_result.choices[0].message.content or content_text
        elif audio_type == "podcast" and sync_client:
            # POD-2: the podcast script is generated by AIService.generate_podcast_script
            # (owns HTML stripping + chunk-and-summarize for long chapters via its own
            # sync_client calls). It is a plain synchronous method — no ``llm_result``/
            # ``usage`` object is produced here, so token tracking for this step is done
            # INSIDE generate_podcast_script's own sync_client calls and is not visible
            # to the ``llm_result is not None`` tracking block below (unchanged for
            # summary/explanation). content_text is passed raw (HTML); strip_html runs
            # inside generate_podcast_script itself.
            tts_input = svc.generate_podcast_script(content_text, chapter_title="") or content_text

        # Track the LLM (script) cost to the INITIATOR's ledger. Failures here are
        # LOGGED at ERROR with stage context — never swallowed, never masking audio.
        if llm_result is not None:
            try:
                llm_tokens = int(getattr(getattr(llm_result, "usage", None), "total_tokens", 0) or 0)
                if llm_tokens > 0:
                    logger.info(
                        "TTS job %s: tracking LLM usage provider=llm user_id=%s "
                        "content_id=%s tokens=%d",
                        job_id, user_id, content_id, llm_tokens,
                    )
                    svc.track_token_usage(user_id, llm_tokens, db)
            except Exception as exc:
                logger.error(
                    "TTS job %s: LLM usage tracking FAILED (provider=llm, "
                    "user_id=%s, content_id=%s): %s",
                    job_id, user_id, content_id, exc, exc_info=True,
                )

        # POD-2: chunk-and-concatenate — never truncate. Only cap at 5000 chars
        # here for the non-podcast (summary/explanation) styles when chunking is
        # unavailable would still be a behavior change, so we ALWAYS route through
        # the chunker; texts under the chunk size resolve to a single chunk,
        # preserving prior behavior byte-for-byte for short inputs.
        from elevenlabs.client import ElevenLabs as EL
        el_client = EL(api_key=ELEVENLABS_API_KEY)

        chunks = _chunk_text_for_tts(tts_input)
        if not chunks:
            # Defensive: the route's own pre-check already rejects empty
            # ``content_text`` before dispatch, but the LLM step above could in
            # theory hand back an empty/whitespace-only script. Fail loudly
            # rather than persist a silent 0-byte "done" audio.
            _finish_error("Texto vazio apos processamento — nada para sintetizar.")
            return
        try:
            audio_bytes = _synthesize_mp3_chunks(el_client, chunks, voice_id)
        except Exception as exc:
            _finish_error(str(exc)[:500])
            return

        # Track the ElevenLabs synthesis cost as a char-equivalent (KISS: summed
        # into the same ``tokens_used`` counter), gated by the feature flag. Provider
        # is labeled in the structured log, NOT in the schema. Tracking failure is
        # logged at ERROR with stage context; the happy path is never masked.
        if cfg.ENABLE_ELEVENLABS_COST_TRACKING:
            try:
                el_chars = len(tts_input)
                if el_chars > 0:
                    logger.info(
                        "TTS job %s: tracking ElevenLabs usage provider=elevenlabs "
                        "user_id=%s content_id=%s char_equivalent=%d",
                        job_id, user_id, content_id, el_chars,
                    )
                    svc.track_token_usage(user_id, el_chars, db)
            except Exception as exc:
                logger.error(
                    "TTS job %s: ElevenLabs usage tracking FAILED "
                    "(provider=elevenlabs, user_id=%s, content_id=%s): %s",
                    job_id, user_id, content_id, exc, exc_info=True,
                )

        subdir = "tts"
        dest_dir = Path(upload_dir) / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}.mp3"
        dest_path = dest_dir / filename
        with open(dest_path, "wb") as f:
            f.write(audio_bytes)

        audio_url = f"/uploads/{subdir}/{filename}"
        word_count = len(tts_input.split())
        duration_minutes = max(1, round(word_count / 150))

        # POD-3/bug #34: persistence is AUTHORITATIVE. `done` is only ever
        # reached when the UPDATE of contents.audio_url/audio_type actually
        # lands (with retries) — a persistence failure becomes `error`, never a
        # phantom `done` pointing at audio the read path can never find again.
        sb = db if db is not None else _safe_create_client(supabase_url, supabase_key)
        if sb is None:
            _finish_error("Falha ao conectar ao banco para persistir o audio gerado.")
            return

        persisted = _persist_audio_url_with_retry(sb, content_id, audio_url, audio_type)
        if not persisted:
            _finish_error(
                "Audio sintetizado, mas falha ao persistir audio_url apos varias tentativas."
            )
            return

        if job_repo is not None:
            try:
                job_repo.mark_done(job_id, audio_url, f"~{duration_minutes} min")
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("TTS job %s: failed to persist done state: %s", job_id, exc)
    except Exception as e:
        _finish_error(str(e)[:200])


def _safe_create_client(supabase_url: str, supabase_key: str):
    """``supabase.create_client`` guarded against connection-time exceptions."""
    try:
        from supabase import create_client
        return create_client(supabase_url, supabase_key)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to create Supabase client for audio_url persistence: %s", exc)
        return None


def _run_tts_job_with_timeout(
    job_id: str,
    content_id: str,
    content_text: str,
    audio_type: str,
    voice_id: str,
    upload_dir: str,
    supabase_url: str,
    supabase_key: str,
    user_id: Optional[str] = None,
) -> None:
    """Wrapper enforcing ``TTS_JOB_TIMEOUT_SECONDS`` on ``_run_tts_job``.

    Runs the real job in a daemon sub-thread and joins with a timeout. If the
    job does not finish in time, the job row is force-marked ``error`` (POD-4:
    a stuck external call must not leave the row in `processing` forever). The
    underlying worker thread is a daemon and is abandoned — Python has no safe
    preemptive thread-kill — but the row is corrected so the poller stops
    waiting, and the process is not blocked from serving other requests.

    Mirrors ``_run_tts_job``'s full (keyword-explicit) signature so the timeout
    boundary can never silently drop/misalign an argument.
    """
    import threading

    worker = threading.Thread(
        target=_run_tts_job,
        kwargs=dict(
            job_id=job_id,
            content_id=content_id,
            content_text=content_text,
            audio_type=audio_type,
            voice_id=voice_id,
            upload_dir=upload_dir,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            user_id=user_id,
        ),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=TTS_JOB_TIMEOUT_SECONDS)

    if worker.is_alive():
        logger.error("TTS job %s exceeded %ds timeout — marking error.", job_id, TTS_JOB_TIMEOUT_SECONDS)
        try:
            from repositories.tts_job_repo import TtsJobRepository
            sb = _safe_create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None
            if sb is not None:
                TtsJobRepository(sb).mark_error(job_id, "Tempo limite excedido na geracao de audio.")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("TTS job %s: failed to persist timeout error: %s", job_id, exc)


# Sweep-on-access is deliberately probabilistic (not on every poll): the
# frontend polls a single in-flight job every few seconds, so gating each of
# those requests on a full terminal-rows scan would add needless latency to
# the hot path. A ~1-in-20 sample keeps `tts_jobs` bounded without that cost.
_TTS_SWEEP_SAMPLE_RATE = 20
_tts_sweep_counter = 0


def _maybe_sweep_expired_jobs(job_repo) -> None:
    """Best-effort, sampled TTL sweep of terminal `tts_jobs` rows (#59).

    Never raises — a sweep failure must not turn a status poll into a 500.
    """
    global _tts_sweep_counter
    _tts_sweep_counter += 1
    if _tts_sweep_counter % _TTS_SWEEP_SAMPLE_RATE != 0:
        return
    try:
        job_repo.sweep_expired(TTS_JOB_TTL)
    except Exception as exc:  # pragma: no cover - defensive, best-effort
        logger.warning("TTS job TTL sweep failed (non-fatal): %s", exc)


@router.post("/api/ai/audio/generate-from-content", tags=["AI - TTS"])
async def audio_generate_from_content(
    body: AudioGenerateRequest,
    current_user: dict = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
    client: Client = Depends(get_supabase),
):
    """Start async audio generation. Returns job_id for polling.

    TTSJOB-2/POD-4: seeds a persisted `processing` row (never a process dict),
    deduplicates concurrent submits for the same (content_id, audio_type), and
    caps the number of jobs a single user may have in flight.
    """
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=503, detail="Audio indisponivel: ELEVENLABS_API_KEY nao configurada.")

    from repositories import ContentRepository
    from repositories.tts_job_repo import TtsJobRepository

    content_repo = ContentRepository(client)
    content_record = content_repo.get_by_id(body.content_id)
    if not content_record:
        raise HTTPException(status_code=404, detail="Conteudo nao encontrado")

    content_text = content_record.get("body") or ""
    if not content_text.strip():
        raise HTTPException(status_code=400, detail="Conteudo sem texto.")

    # TKN-5: budget pre-check BEFORE the paid synthesis thread is dispatched. A
    # user over the daily token limit is barred at the source — no thread, no
    # ElevenLabs call, no LLM call. The TKN-3 budget enforcer reads PERSISTED daily
    # usage; an over-cap user raises ``AIServiceError`` -> 503. The read is sync, so
    # it runs off the event loop. ``user_id`` is the INITIATOR, captured here at
    # enqueue time and propagated to the worker (never derived inside the thread).
    svc = get_ai_service()
    user_id = current_user["id"]
    try:
        await run_in_threadpool(svc.check_token_budget, user_id, client)
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))

    job_repo = TtsJobRepository(client)

    # POD-4: dedup by (content_id, audio_type) — a different audio_type for the
    # SAME content is NOT blocked (each style gets its own job). The check + seed
    # is guarded by a process-local lock so two near-simultaneous submits in this
    # worker cannot both pass the "no active job" check before either writes its
    # row (this deploy is single-worker — see CLAUDE.md — so a process-local lock
    # is sufficient; it is not meant to replace a DB-level uniqueness guarantee).
    with _dispatch_lock():
        active = await run_in_threadpool(
            job_repo.get_active_for_content, body.content_id, body.audio_type, user_id
        )
        if active is not None:
            return {"job_id": active["id"], "status": "processing"}

        # POD-4: cap concurrent in-flight jobs per user — a user way over their
        # limit is barred with a clear 429 instead of spawning unbounded threads.
        active_count = await run_in_threadpool(job_repo.count_active_for_user, user_id)
        if active_count >= TTS_MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(
                status_code=429,
                detail=f"Limite de {TTS_MAX_ACTIVE_JOBS_PER_USER} audios em geracao simultanea atingido. Aguarde a conclusao de um job em andamento.",
            )

        voice_id = body.voice if body.voice in ELEVENLABS_VOICES else "21m00Tcm4TlvDq8ikWAM"
        job_id = uuid4().hex
        await run_in_threadpool(
            job_repo.seed_processing, job_id, body.content_id, user_id, body.audio_type
        )

    cfg = get_settings()
    import threading
    t = threading.Thread(
        target=_run_tts_job_with_timeout,
        args=(job_id, body.content_id, content_text, body.audio_type, voice_id,
              str(storage.base_dir), cfg.SUPABASE_URL, cfg.SUPABASE_KEY, user_id),
        daemon=True,
    )
    t.start()

    return {"job_id": job_id, "status": "processing"}


@router.get("/api/ai/audio/status/{job_id}", tags=["AI - TTS"])
async def audio_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    """Poll TTS job status. Returns processing/done/error.

    TTSJOB-2 (bug #58/#59/#60): reads the persisted `tts_jobs` row WITHOUT any
    pop/delete — two consecutive polls after `done` return the same payload.
    Ownership is enforced via ``TtsJobRepository`` (which never filters by
    ``job_id`` alone), so a cross-user actor gets 404, never another user's job.
    """
    from repositories.tts_job_repo import TtsJobRepository

    job_repo = TtsJobRepository(client)
    # #59: TTL sweep, check-on-access — cheap and best-effort. Only terminal
    # (`done`/`error`) rows are ever candidates (enforced inside sweep_expired
    # itself); a sweep failure never blocks the status read.
    await run_in_threadpool(_maybe_sweep_expired_jobs, job_repo)
    job = await run_in_threadpool(job_repo.get_by_id, job_id)

    if job is not None:
        # IDOR guard: a job row exists but belongs to someone else -> 404 (never
        # leak existence/content of another user's job).
        if str(job.get("user_id")) != str(current_user["id"]):
            raise HTTPException(status_code=404, detail="Job nao encontrado")
        return _tts_job_response(job)

    # Fallback (TTSJOB-2 AC): the job row is gone (swept by TTL, or the poller
    # is retrying an id from before persistence landed). We cannot recover the
    # job's content_id once the row itself is gone, so we cannot re-derive
    # ``contents.audio_url`` for it here — a genuinely-unknown job_id (never
    # existed, wrong id, or already swept) is a straightforward 404. Callers
    # polling a still-fresh job never hit this branch: `done`/`error` rows are
    # only removed after ``TTS_JOB_TTL`` (24h), far longer than the frontend's
    # ~90s polling window.
    raise HTTPException(status_code=404, detail="Job nao encontrado")


def _tts_job_response(job: dict) -> dict:
    """Shape a persisted `tts_jobs` row into the poller's expected payload —
    same field names the dict-based implementation returned, so the frontend
    contract is unchanged."""
    status = job.get("status", "processing")
    payload: Dict[str, Any] = {"status": status}
    if status == "done":
        payload["audio_url"] = job.get("audio_url")
        payload["duration_estimate"] = job.get("duration_estimate")
        payload["audio_type"] = job.get("audio_type")
    elif status == "error":
        payload["detail"] = job.get("error") or "Falha na geracao de audio."
    return payload


class ReprocessContentRequest(BaseModel):
    content_id: str = Field(..., min_length=1)


@router.post("/api/ai/reprocess-content", tags=["AI"])
async def reprocess_content(
    body: ReprocessContentRequest,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    """Reprocess content body with AI to improve formatting and readability."""
    from repositories import ContentRepository

    content_repo = ContentRepository(client)
    record = content_repo.get_by_id(body.content_id)
    if not record:
        raise HTTPException(status_code=404, detail="Conteudo nao encontrado")

    raw_body = record.get("body") or ""
    if not raw_body.strip():
        raise HTTPException(status_code=400, detail="Conteudo vazio — nada para reprocessar")

    svc = get_ai_service()
    if not svc.client:
        raise HTTPException(status_code=503, detail="Servico de IA indisponivel")

    try:
        # ASYNC-AI-1: ``svc.client`` is now AsyncOpenAI; this is an async handler on
        # the event loop, so the call must be awaited (was a blocking sync call that
        # froze the loop for the whole reformatting turn).
        result = await svc.client.chat.completions.create(
            model=svc.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Voce e um formatador de texto academico. Recebera um texto extraido de um PDF que pode estar "
                        "mal formatado (com tags HTML residuais, tabelas quebradas, numeros de slide soltos, frases "
                        "cortadas, etc). Seu trabalho:\n"
                        "1. Limpar TODA formatacao ruim (remover <br>, tags HTML, caracteres estranhos)\n"
                        "2. Reconstruir paragrafos quebrados em frases completas\n"
                        "3. Organizar em secoes com titulos markdown (## Titulo)\n"
                        "4. Preservar TODO o conteudo original — nao inventar, nao resumir, nao omitir\n"
                        "5. Tabelas devem virar listas ou markdown tables limpas\n"
                        "6. Manter em portugues\n"
                        "7. Retornar APENAS o texto formatado em Markdown, sem explicacoes adicionais"
                    ),
                },
                {"role": "user", "content": raw_body[:15000]},
            ],
            max_tokens=4000,
            temperature=0.1,
        )
        improved = result.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"AI reprocess failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Falha ao reprocessar com IA")

    if not improved.strip():
        return {"body": raw_body, "reprocessed": False, "message": "IA nao conseguiu melhorar o conteudo"}

    # Save improved body to DB
    content_repo.update(body.content_id, {"body": improved.strip()})

    return {
        "body": improved.strip(),
        "reprocessed": True,
        "original_length": len(raw_body),
        "new_length": len(improved.strip()),
    }


@router.get("/api/ai/tts/status", tags=["AI - TTS"])
async def tts_status():
    enabled = bool(ELEVENLABS_API_KEY)
    return {
        "enabled": enabled,
        "provider": "elevenlabs" if enabled else None,
        "model": "eleven_multilingual_v2" if enabled else None,
    }


@router.post("/api/ai/transcribe", tags=["AI - TTS"])
async def ai_transcribe(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    svc = get_ai_service()
    if svc.mock_mode or svc.client is None:
        raise HTTPException(
            status_code=503,
            detail="Transcricao indisponivel: OPENAI_API_KEY nao configurada ou em mock mode.",
        )

    try:
        content = await file.read()
    except Exception as e:
        logger.error(f"Transcribe file read failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Falha ao ler arquivo enviado.")

    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    # Whisper expects a file-like object; passing a (name, bytes, mime) tuple is supported.
    upload_name = file.filename or "audio.webm"
    mime_type = file.content_type or "application/octet-stream"

    # ASYNC-AI-2: ``svc.client`` is now AsyncOpenAI (ASYNC-AI-1), so Whisper runs
    # awaited — the long upload+inference no longer blocks the single event loop.
    # The timeout configured on the async client (ASYNC-AI-1) maps an upstream
    # stall to an exception which is caught below and surfaced as 502/504.
    try:
        result = await svc.client.audio.transcriptions.create(
            model="whisper-1",
            file=(upload_name, content, mime_type),
        )
        text = getattr(result, "text", "") or ""
    except Exception as e:
        logger.error(f"Whisper transcribe failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Falha na chamada Whisper: {sanitize_ai_error(e)}")

    return {
        "status": "ok",
        "text": text,
        "model": "whisper-1",
    }


# ===================================================================
# CHAT SESSION ENDPOINTS
# ===================================================================


def _create_chat_session_row(
    client: Client, uid: str, content_id: str, initial_question_text: str | None = None
) -> dict:
    """Insert a fresh, distinct active session (used for the completed→new-attempt
    path, where a duplicate row is the intended product behavior — SEC-CHAT-3).

    SOC-1: ``initial_question_text`` (when provided) is written on creation so the
    chosen "Pergunta para Reflexão" is the durable source of truth for the lock.

    P0 (nova-tentativa fix): the DB enforces at most ONE ``active`` session per
    ``(user_id, content_id)``. The caller resolves only the NEWEST row for the
    pair, so an older ``active`` attempt hidden behind a newer ``completed`` row
    (GRD-2 phantom / clock ties / races) makes this insert violate that unique
    index → the whole "Refazer sessão" 500s. On a unique violation we recover by
    resuming the surviving ``active`` row instead of surfacing the error; any
    other failure still propagates.
    """
    new_session = {
        "user_id": uid,
        "content_id": content_id,
        "status": "active",
        "total_messages": 0,
    }
    if initial_question_text is not None:
        new_session["initial_question_text"] = initial_question_text
    try:
        insert_result = client.table("chat_sessions").insert(new_session).execute()
        return insert_result.data[0] if insert_result.data else new_session
    except Exception as exc:
        msg = str(exc).lower()
        if "unique" not in msg and "duplicate" not in msg and "23505" not in msg:
            raise
        row = _get_active_session_row(client, uid, content_id)
        if row:
            return _ensure_initial_question(client, row, initial_question_text)
        raise


def _get_active_session_row(client: Client, uid: str, content_id: str) -> dict | None:
    """Newest ``active`` session for the pair, or None. ``.order().limit(1)`` keeps
    ``.maybe_single()`` safe even if legacy data holds >1 active row (GRD-3)."""
    res = client.table("chat_sessions").select("*").eq(
        "user_id", uid
    ).eq("content_id", content_id).eq("status", "active").order(
        "created_at", desc=True
    ).limit(1).maybe_single().execute()
    return getattr(res, "data", None) if res else None


def _ensure_initial_question(
    client: Client, session: dict, initial_question_text: str | None
) -> dict:
    """SOC-1 first-write-wins for ``initial_question_text`` (idempotent).

    Writes the question ONLY when the stored value is still NULL (a freshly
    upserted row, or a legacy session created before this column existed) AND the
    request actually carries one. A non-null stored value is NEVER overwritten,
    even if the request brings a different question — the first choice is
    permanent while the session lives. Returns the (possibly updated) row so the
    route always responds with the authoritative stored question.
    """
    if not initial_question_text:
        return session
    if session.get("initial_question_text"):
        return session
    updated = client.table("chat_sessions").update(
        {"initial_question_text": initial_question_text}
    ).eq("id", session["id"]).execute()
    return updated.data[0] if getattr(updated, "data", None) else {
        **session, "initial_question_text": initial_question_text
    }


def _upsert_chat_session_row(
    client: Client, uid: str, content_id: str, initial_question_text: str | None = None
) -> dict:
    """Race-free create-or-get for (uid, content_id) (TPP-2, bug #7).

    Prefers the ``upsert_chat_session`` RPC (DB ``ON CONFLICT`` — two concurrent
    callers resolve to the same row, never two, never a 500). Degrades to a guarded
    insert when the RPC is unavailable (un-migrated DB / in-memory fake): re-reads
    on a conflict so the surviving row is still returned rather than surfacing a
    duplicate-key error to the user.
    """
    rpc = getattr(client, "rpc", None)
    if callable(rpc):
        try:
            res = rpc(
                "upsert_chat_session",
                {"p_user_id": uid, "p_content_id": content_id},
            ).execute()
            row = getattr(res, "data", None)
            if isinstance(row, list):
                row = row[0] if row else None
            if row:
                # SOC-1: the RPC signature does not carry the question, so persist
                # it here (write-once). On the ON CONFLICT path this row may be an
                # existing session — _ensure_initial_question keeps first-write-wins.
                return _ensure_initial_question(client, row, initial_question_text)
        except Exception as exc:
            logger.warning(
                "upsert_chat_session RPC failed for (%s, %s): %s; falling back",
                uid, content_id, exc,
            )

    # Fallback: insert, and if a concurrent insert won the race, re-read the
    # surviving row instead of propagating the unique-violation as a 500.
    # GRD-3 it3 (twin of the it2 fix): ``(user_id, content_id)`` is NOT unique after
    # any restart / GRD-2 phantom (SEC-CHAT-3 keeps completed rows alongside new
    # attempts), so this re-read must ALSO resolve the MOST RECENT row via
    # ``.order().limit(1)`` — a bare ``.maybe_single()`` here would raise PGRST116 on
    # >1 row and re-surface the exact 500 the it2 fix removed, only on the race path.
    try:
        return _create_chat_session_row(client, uid, content_id, initial_question_text)
    except Exception:
        existing = client.table("chat_sessions").select("*").eq(
            "user_id", uid
        ).eq("content_id", content_id).order("created_at", desc=True).limit(1).maybe_single().execute()
        row = getattr(existing, "data", None)
        if row:
            return _ensure_initial_question(client, row, initial_question_text)
        raise


@router.post("/chat-sessions", tags=["Chat Sessions"])
async def create_or_get_chat_session(
    data: ChatSessionCreate,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    try:
        # SEC-AUTHZ-0 (bug #2) + TPP-2: the owner is ALWAYS the authenticated user.
        # A client-supplied ``data.user_id`` is never trusted — if present and
        # pointing elsewhere, ``assert_owner_or_role`` rejects the spoof (a STUDENT
        # cannot create/own a session for another user_id) and it never reaches any
        # SELECT/INSERT/UPSERT below.
        uid = current_user["id"]
        if data.user_id is not None:
            assert_owner_or_role(data.user_id, current_user, "ADMIN", "TEACHER", "INSTRUCTOR")

        # GRD-3 (refazer loop fix): resolve the MOST RECENT session for this pair, not
        # a bare ``.maybe_single()``. After any "Refazer sessão" or a GRD-2 phantom,
        # ``(user_id, content_id)`` legitimately has ≥2 rows (SEC-CHAT-3 keeps the
        # completed one alongside the new attempt). A bare ``.maybe_single()`` raises
        # on >1 row (PGRST116) → the endpoint 500s or resolves an ambiguous/stale
        # completed row, so the kickoff runs against a FINISHED session
        # (count_user_messages >= MAX → remaining 0 / finalized) and the UI snaps back
        # to "Sessão concluída" — the dead loop Hugo hit. Ordering by newest and taking
        # one mirrors ``get_session_by_content`` (see the note at that endpoint) so the
        # newest session (the fresh active attempt) is the one evaluated.
        result = client.table("chat_sessions").select("*").eq(
            "user_id", uid
        ).eq(
            "content_id", data.content_id
        ).order("created_at", desc=True).limit(1).maybe_single().execute()

        existing = result.data if result else None

        if existing:
            # SEC-CHAT-3: only ``abandoned`` sessions may be reactivated. A
            # ``completed`` session is NEVER forced back to ``active`` — doing so
            # would wipe the completion marker and merge the prior transcript into a
            # new attempt. ``completed`` falls through to create a fresh session for
            # the new attempt; ``active`` is simply resumed as-is.
            if existing.get("status") == "abandoned":
                updated = client.table("chat_sessions").update(
                    {"status": "active"}
                ).eq("id", existing["id"]).execute()
                row = updated.data[0] if updated.data else existing
                # SOC-1: a reactivated session keeps its original question; only a
                # legacy NULL is backfilled from the request (first-write-wins).
                return _ensure_initial_question(client, row, data.initial_question_text)
            if existing.get("status") != "completed":
                # SOC-1: resuming an ``active`` session NEVER overwrites the stored
                # question — the request may carry a different one and it is ignored;
                # a legacy NULL is backfilled once.
                return _ensure_initial_question(client, existing, data.initial_question_text)
            # status == "completed": fall through to create a new, distinct session.
            # (The partial unique index allows this because the completed row stays;
            # a deliberate "new attempt after completion" is a product decision —
            # SEC-CHAT-3 — handled here at the app layer.) SOC-1: the new attempt
            # gets the NEW question written on creation.
            #
            # P0 (nova-tentativa fix): the newest row being ``completed`` does NOT
            # guarantee the pair has no ``active`` row — an older active attempt can
            # survive behind it (GRD-2 phantom / clock ties). Inserting a 2nd active
            # would violate the one-active-per-pair unique index → 500. Resume the
            # stranded active attempt when it exists; only create when none does.
            stranded_active = _get_active_session_row(client, uid, data.content_id)
            if stranded_active:
                return _ensure_initial_question(
                    client, stranded_active, data.initial_question_text
                )
            return _create_chat_session_row(
                client, uid, data.content_id, data.initial_question_text
            )

        # TPP-2: no existing session → race-free create-or-get. Two concurrent
        # double-submits for the same (user_id, content_id) both resolve to the SAME
        # row via the ``upsert_chat_session`` RPC (ON CONFLICT in the DB), so neither
        # creates a duplicate nor hits the permanent-500 maybe_single() failure (#7).
        return _upsert_chat_session_row(
            client, uid, data.content_id, data.initial_question_text
        )
    except HTTPException:
        # Authorization decisions (e.g. the 403 spoof rejection above) must keep
        # their status code — never be masked as a 500 by the generic handler.
        raise
    except Exception as e:
        logger.error(f"create_or_get_chat_session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.get("/chat-sessions/{session_id}", tags=["Chat Sessions"])
async def get_chat_session(
    session_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    # SEC-CHAT-1: load the session, then assert ownership BEFORE reading messages.
    # A cross-user STUDENT gets 403/404 and no chat_messages query fires.
    session = load_session_or_404(client, session_id)
    assert_owner_or_role(
        session.get("user_id"), current_user, "ADMIN", "TEACHER", "INSTRUCTOR"
    )

    # TPP-3: read via the repo so transcript order uses the stable
    # (created_at, sequence, id) tiebreaker — no microsecond reordering.
    session["messages"] = await run_in_threadpool(
        ChatRepository(client).get_session_messages, session_id
    )
    return session


@router.get("/chat-sessions/{session_id}/messages", tags=["Chat Sessions"])
async def get_session_messages(
    session_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    # SEC-CHAT-1: resolve the parent session and assert ownership BEFORE returning
    # any messages. A cross-user actor gets 403/404 with zero message rows leaked.
    session = load_session_or_404(client, session_id)
    assert_owner_or_role(
        session.get("user_id"), current_user, "ADMIN", "TEACHER", "INSTRUCTOR"
    )

    # TPP-3/TPP-4: stable-ordered transcript (created_at, sequence, id). After TPP-4
    # this returns BOTH the student (role='user') and tutor (role='assistant')
    # turns persisted server-side, so a reload shows the full socratic dialogue.
    return await run_in_threadpool(
        ChatRepository(client).get_session_messages, session_id
    )


@router.post("/chat-sessions/{session_id}/messages", tags=["Chat Sessions"])
async def add_session_message(
    session_id: str,
    data: ChatMessageCreate,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    # SEC-CHAT-2: load the session WITH its owner (``user_id``) and gate ownership
    # BEFORE building/inserting the message. A non-owner STUDENT enumerating a
    # session_id gets 403 and NO message is inserted (the check precedes the insert);
    # a privileged role (TEACHER/ADMIN/INSTRUCTOR) may still add. Missing -> 404.
    session = load_session_or_404(client, session_id)
    assert_owner_or_role(
        session.get("user_id"), current_user, "ADMIN", "TEACHER", "INSTRUCTOR"
    )

    new_message = {
        "role": data.role,
        "content": data.content,
        "agent_type": data.agent_type,
        "metadata": data.metadata,
    }

    try:
        # TPP-3: single write path. ``persist_turn`` inserts the message AND bumps
        # ``total_messages`` atomically (RPC), so the counter never drifts and there
        # is no inline read-modify-write to lose an update (#40). Wrapped in a
        # threadpool to keep the sync Supabase client off the event loop (ASYNC-AI-1).
        return await run_in_threadpool(
            ChatRepository(client).persist_turn, session_id, new_message
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao salvar mensagem")


@router.get("/chat-sessions/by-content/{content_id}", tags=["Chat Sessions"])
async def get_session_by_content(
    content_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    # DATA-GAM-3 guard: SEC-CHAT-3 lets a completed session coexist with a fresh
    # "new attempt" row for the same (content_id, user_id), so this pair is NOT
    # guaranteed unique. A bare ``.maybe_single()`` would 500 on >1 row; order by
    # newest and take one so the caller reliably gets the most recent session.
    # (This is only the cheap guard; the full status machine is DATA-GAM-4.)
    result = client.table("chat_sessions").select("*").eq(
        "content_id", content_id
    ).eq(
        "user_id", current_user["id"]
    ).order("created_at", desc=True).limit(1).maybe_single().execute()

    # GRD-5 (resume 500): supabase-py 2.28.x returns ``None`` (not ``_Result(data=
    # None)``) from ``.maybe_single().execute()`` when the student has NO session for
    # this content. A bare ``result.data`` raised AttributeError -> HTTP 500, which the
    # frontend's ``byContent(...).catch(() => null)`` did NOT treat as "no session"
    # (it expects a 404), so the chapter's resume hydration failed with
    # "Chat resume error: 500". Guard the None so the empty case yields the intended
    # 404. Precedent: commit 5847a60 (same fix in BaseRepository.get_by_id).
    session = result.data if result is not None else None
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada para este conteudo")
    return session


@router.get("/users/{user_id}/chat-sessions", tags=["Chat Sessions"])
async def get_user_chat_sessions(
    user_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    # SEC-CHAT-1: the path ``user_id`` is the *target*, never the trusted identity.
    # A STUDENT may only list their own sessions; TEACHER/ADMIN/INSTRUCTOR may list
    # any user's. The decision runs BEFORE the query, so a cross-user STUDENT gets
    # 403 with no rows returned.
    require_self_or_role(user_id, current_user, "ADMIN", "TEACHER", "INSTRUCTOR")

    result = client.table("chat_sessions").select("*").eq(
        "user_id", user_id
    ).order("created_at", desc=True).execute()
    return result.data or []


async def _apply_session_completion(client: Client, session: dict) -> dict:
    """Server-side active→completed transition for a socratic session (SOC-2/GRD-2).

    Single source of truth for "mark this session completed", shared by the
    ``PUT .../complete`` endpoint AND the socratic finalizer path (SOC-2: the turn
    that returns ``should_finalize`` must not leave a zombie ``active`` session).
    Ownership MUST already be gated by the caller — this helper only performs the
    transition and NEVER makes an authorization decision.

    Guarantees (unchanged from the endpoint that formerly inlined this):
      * Idempotent: an already-``completed`` session is a no-op (no redundant write,
        so the DATA-GAM-3 score edge below runs exactly once — never on re-complete).
      * GRD-2 phantom guard: refuses to complete a session with zero real student
        turns; the session is returned unchanged (still ``active``).
      * DATA-GAM-3: computes ``performance_score`` best-effort and persists it with
        the status flip on this transition only; a computation failure leaves the
        score NULL and NEVER blocks completion.

    Returns the (possibly updated) session row.
    """
    session_id = session["id"]

    # Idempotency: a 2nd complete on an already-completed session is a no-op — no
    # redundant write is issued, so the score is computed/persisted ONLY on the first
    # active->completed transition (DATA-GAM-3 AC: score written exactly once).
    if session.get("status") == "completed":
        return session

    # GRD-2 (phantom session): a session may only be completed AFTER at least one real
    # student turn. The completion authority is server-side — never the frontend's
    # localStorage ``tutorDone`` flag. ``count_user_messages`` is the canonical on-read
    # count of ``role='user'`` turns; zero → no completion, the session stays as-is.
    user_turns = await run_in_threadpool(
        ChatRepository(client).count_user_messages, session_id
    )
    if user_turns <= 0:
        return session

    # DATA-GAM-3: additive hook on the completion edge. Load the persisted turns,
    # compute the gamification/progress ``performance_score`` from them, and persist
    # it together with the status flip — once, on this transition only. Best-effort:
    # any failure leaves ``performance_score`` NULL and NEVER blocks completion.
    update_payload: Dict[str, Any] = {"status": "completed"}
    try:
        turns = await run_in_threadpool(
            ChatRepository(client).get_session_messages, session_id
        )
        score = compute_performance_score(turns)
        if score is not None:
            update_payload["performance_score"] = score
    except Exception as exc:  # pragma: no cover - score is additive, never blocking
        logger.warning(
            "_apply_session_completion: performance_score computation failed (%s): %s",
            session_id, exc,
        )

    updated = client.table("chat_sessions").update(
        update_payload
    ).eq("id", session_id).execute()

    return updated.data[0] if updated.data else {"id": session_id, **update_payload}


@router.put("/chat-sessions/{session_id}/complete", tags=["Chat Sessions"])
async def complete_chat_session(
    session_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    # SEC-CHAT-3: load the session WITH owner + status, then gate ownership BEFORE
    # any write. A cross-user actor gets 403 (404 if missing) and the status is left
    # untouched — identity is always current_user, never body/path.
    session = load_session_or_404(client, session_id)
    assert_owner_or_role(
        session.get("user_id"), current_user, "ADMIN", "TEACHER", "INSTRUCTOR"
    )

    # The transition (idempotency + GRD-2 guard + DATA-GAM-3 score + status flip) is
    # centralized in ``_apply_session_completion`` so this endpoint and the socratic
    # finalizer path share ONE completion authority (SOC-2). Ownership is gated above.
    return await _apply_session_completion(client, session)


@router.post("/chat-sessions/{session_id}/export-moodle", tags=["Chat Sessions"])
async def export_session_moodle(
    session_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    # SEC-CHAT-1 / SEC-CHAT-4: ownership gate runs BEFORE loading messages and the
    # user PII (name/email). A non-owner gets 403/404 and zero chat_messages/users
    # queries fire — no transcript, name or email of a stranger's session can leak.
    session = load_session_or_404(client, session_id)
    assert_owner_or_role(
        session.get("user_id"), current_user, "ADMIN", "TEACHER", "INSTRUCTOR"
    )

    # TPP-4: export the FULL transcript (both user and assistant turns, stable
    # order) now that the socratic questions are persisted server-side.
    session["messages"] = await run_in_threadpool(
        ChatRepository(client).get_session_messages, session_id
    )
    session["session_id"] = session["id"]

    # Fetch user info for export — the actor is the OWNER of the loaded session
    # (session["user_id"]), never a body/path-supplied identity.
    user_result = client.table("users").select("name, email").eq(
        "id", session.get("user_id", "")
    ).maybe_single().execute()

    # GRD-5: guard the zero-row ``None`` from ``.maybe_single().execute()`` (a session
    # whose owner was deleted would otherwise 500 here). Precedent: commit 5847a60.
    user_data = user_result.data if user_result is not None else None
    session["user_name"] = user_data.get("name", "") if user_data else ""
    session["user_email"] = user_data.get("email", "") if user_data else ""

    svc = get_ai_service()
    return svc.prepare_moodle_export(session)


# ===================================================================
# INTEGRATION ENDPOINTS
# ===================================================================


@router.post("/integrations/test-connection", tags=["Integrations"])
async def integration_test_connection(
    system: str = Query(...),
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN", "TEACHER")),
):
    return await svc.test_connection(system)


@router.get("/integrations/status", tags=["Integrations"])
async def integration_status(
    svc: IntegrationService = Depends(get_integration_service),
    # SEC-SCOPE-4: was fully unauthenticated; now ADMIN-only, mirroring the sibling
    # integration_logs gate. require_role resolves BEFORE svc.get_status(), so no
    # JACAD/Moodle probe fires for anonymous/STUDENT callers.
    current_user: dict = Depends(require_role("ADMIN")),
):
    return await svc.get_status()


@router.get("/integrations/logs", tags=["Integrations"])
async def integration_logs(
    system: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=200),
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN")),
):
    filters = {}
    if system:
        filters["system"] = system
    if status:
        filters["status"] = status
    return await svc.get_logs(filters, limit)


@router.get("/integrations/mappings", tags=["Integrations"])
async def integration_mappings(
    entity_type: Optional[str] = None,
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN")),
):
    return await svc.get_mappings(entity_type)


# ---- Integration mock guard ----

def _require_live_integration(use_mock: bool, system: str, env_vars: str) -> None:
    """Raise 503 if integration client is in mock mode.

    Protects write operations (sync, import, export) from polluting production DB
    with hardcoded mock data like 'Maria Silva' / 'Joao Santos'.
    """
    if use_mock:
        raise HTTPException(
            status_code=503,
            detail=f"{system} nao configurado. Configure {env_vars} para habilitar esta operacao.",
        )


# ---- JACAD ----

@router.post("/integrations/jacad/sync", tags=["Integrations - JACAD"])
async def jacad_sync(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN")),
):
    _require_live_integration(svc.jacad.use_mock, "JACAD", "JACAD_BASE_URL e JACAD_API_KEY")
    users_result = await svc.sync_users_from_jacad()
    disc_result = await svc.sync_disciplines_from_jacad()
    return {"users": users_result.to_dict(), "disciplines": disc_result.to_dict()}


@router.post("/integrations/jacad/import-students", tags=["Integrations - JACAD"])
async def jacad_import_students(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN")),
):
    _require_live_integration(svc.jacad.use_mock, "JACAD", "JACAD_BASE_URL e JACAD_API_KEY")
    result = await svc.sync_users_from_jacad()
    return result.to_dict()


@router.post("/integrations/jacad/import-disciplines", tags=["Integrations - JACAD"])
async def jacad_import_disciplines(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN")),
):
    _require_live_integration(svc.jacad.use_mock, "JACAD", "JACAD_BASE_URL e JACAD_API_KEY")
    result = await svc.sync_disciplines_from_jacad()
    return result.to_dict()


@router.get("/integrations/jacad/student/{ra}", tags=["Integrations - JACAD"])
async def jacad_student(
    ra: str,
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN", "TEACHER")),
):
    student = await svc.get_jacad_student(ra)
    if not student:
        raise HTTPException(status_code=404, detail="Aluno nao encontrado no JACAD")
    return student


# ---- Moodle ----

@router.post("/integrations/moodle/sync", tags=["Integrations - Moodle"])
async def moodle_sync(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN")),
):
    _require_live_integration(svc.moodle.use_mock, "Moodle", "MOODLE_URL e MOODLE_TOKEN")
    export_result = await svc.export_sessions_to_moodle()
    import_result = await svc.import_ratings_from_moodle()
    return {"export": export_result.to_dict(), "import": import_result.to_dict()}


@router.post("/integrations/moodle/import-users", tags=["Integrations - Moodle"])
async def moodle_import_users(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN")),
):
    _require_live_integration(svc.moodle.use_mock, "Moodle", "MOODLE_URL e MOODLE_TOKEN")
    result = await svc.import_users_from_moodle()
    return result.to_dict()


@router.post("/integrations/moodle/export-sessions", tags=["Integrations - Moodle"])
async def moodle_export_sessions(
    filters: Optional[dict] = None,
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN", "TEACHER")),
):
    _require_live_integration(svc.moodle.use_mock, "Moodle", "MOODLE_URL e MOODLE_TOKEN")
    result = await svc.export_sessions_to_moodle(filters)
    return result.to_dict()


@router.get("/integrations/moodle/ratings", tags=["Integrations - Moodle"])
async def moodle_ratings(
    session_id: Optional[str] = None,
    svc: IntegrationService = Depends(get_integration_service),
    current_user: dict = Depends(require_role("ADMIN", "TEACHER")),
):
    filters = {}
    if session_id:
        filters["session_id"] = session_id
    return await svc.get_moodle_ratings(filters)


# Header the Moodle plugin sends the HMAC-SHA256 of the raw body in.
MOODLE_WEBHOOK_SIGNATURE_HEADER = "X-Moodle-Signature"


def _resolve_moodle_webhook_secret(client: Client) -> str:
    """Resolve the Moodle webhook shared secret (SEC-SCOPE-5).

    Precedence:
      1. ``MOODLE_WEBHOOK_SECRET`` env var (operator override / deploy-time).
      2. ``system_settings.moodle_webhook_secret`` (admin-managed, sensitive field).

    Returns an empty string when no secret is configured anywhere; the caller
    applies the fail-closed (prod) / warn (dev) policy.
    """
    env_secret = os.getenv("MOODLE_WEBHOOK_SECRET", "")
    if env_secret:
        return env_secret
    try:
        res = (
            client.table("system_settings")
            .select("moodle_webhook_secret")
            .limit(1)
            .maybe_single()
            .execute()
        )
        data = getattr(res, "data", None) if res is not None else None
        if data:
            return data.get("moodle_webhook_secret") or ""
    except Exception as e:  # pragma: no cover - defensive: never leak DB errors here
        logger.warning(f"Failed to read moodle_webhook_secret from system_settings: {e}")
    return ""


@router.post("/integrations/moodle/webhook", tags=["Integrations - Moodle"])
async def moodle_webhook(
    request: Request,
    svc: IntegrationService = Depends(get_integration_service),
    client: Client = Depends(get_supabase),
):
    # SEC-SCOPE-5: authenticate the webhook via HMAC over the RAW body BEFORE any
    # dispatch (so it covers rating_submitted and any future event_type). No body
    # field is trusted for authorization — only the signature over the raw bytes.
    raw_body = await request.body()
    signature = request.headers.get(MOODLE_WEBHOOK_SIGNATURE_HEADER)
    secret = _resolve_moodle_webhook_secret(client)

    settings = get_settings()
    is_production = settings.ENVIRONMENT.lower() == "production"

    if not secret:
        if is_production:
            # Fail-closed: never accept an unauthenticated webhook in production.
            logger.warning("Moodle webhook rejected: no moodle_webhook_secret configured (production).")
            raise HTTPException(status_code=401, detail="Webhook nao autenticado")
        # Non-production: warn but allow the dev path so local testing is not blocked.
        logger.warning(
            "Moodle webhook secret not configured; accepting request in non-production "
            "(ENVIRONMENT=%s). Configure MOODLE_WEBHOOK_SECRET / system_settings to "
            "enforce HMAC.",
            settings.ENVIRONMENT,
        )
    else:
        # Verify HMAC over the exact raw body using constant-time comparison.
        if not verify_moodle_webhook_signature(raw_body, signature, secret):
            logger.warning("Moodle webhook rejected: invalid or missing HMAC signature.")
            raise HTTPException(status_code=401, detail="Assinatura invalida")

    try:
        body = json.loads(raw_body) if raw_body else {}
        if not isinstance(body, dict):
            raise ValueError("payload is not an object")
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Payload invalido")

    event_type = body.get("event_type", "unknown")
    return await svc.handle_moodle_webhook(event_type, body)


# ===================================================================
# LTI ENDPOINTS
# ===================================================================


@router.post("/lti/launch", tags=["LTI"])
async def lti_launch(
    request: Request,
    client: Client = Depends(get_supabase),
):
    settings = get_settings()
    lti_key = os.getenv("LTI_CONSUMER_KEY", "")
    lti_secret = os.getenv("LTI_SHARED_SECRET", "")
    lti_enabled = os.getenv("LTI_ENABLED", "false").lower() == "true"
    redirect_url = os.getenv("LTI_REDIRECT_URL", settings.FRONTEND_URL)

    if not lti_enabled:
        raise HTTPException(status_code=403, detail="LTI nao habilitado")

    form_data = await request.form()
    params = {k: v for k, v in form_data.items()}
    url = str(request.url).split("?")[0]

    try:
        launch_data = await validate_lti_launch(params, url, lti_key, lti_secret)
    except LTIValidationError as e:
        logger.error(f"LTI validation error: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="Authentication failed")

    # Find or create user
    user = None
    if launch_data.ra:
        result = (client.table("users").select("*").eq("ra", launch_data.ra).maybe_single().execute() or type("_R", (), {"data": None})())
        user = result.data
    if not user and launch_data.email:
        result = (client.table("users").select("*").eq("email", launch_data.email).maybe_single().execute() or type("_R", (), {"data": None})())
        user = result.data

    # SEC-SCOPE-6: auto-create is opt-in (default false) and never grants ADMIN.
    auto_create = os.getenv("LTI_AUTO_CREATE_USERS", "false").lower() == "true"
    if not user and auto_create:
        from auth import hash_password
        new_user = {
            "ra": launch_data.ra or f"lti-{launch_data.user_id}",
            "name": launch_data.name or "LTI User",
            "email": launch_data.email,
            # launch_data.role is already capped to STUDENT/TEACHER by
            # _map_lti_roles (administrator can never reach here).
            "role": launch_data.role,
            # SEC-SCOPE-6: never derive the password from a known/loggable id
            # (RA/user_id). Use a random, unusable secret so a created LTI account
            # cannot be logged into directly via /auth/login.
            "password_hash": hash_password(secrets.token_urlsafe(32)),
            "moodle_user_id": launch_data.user_id,
        }
        insert_result = client.table("users").insert(new_user).execute()
        user = insert_result.data[0] if insert_result.data else None
    elif user:
        updates = {}
        if launch_data.name and user.get("name") != launch_data.name:
            updates["name"] = launch_data.name
        if not user.get("moodle_user_id"):
            updates["moodle_user_id"] = launch_data.user_id
        if updates:
            update_result = client.table("users").update(updates).eq("id", user["id"]).execute()
            user = update_result.data[0] if update_result.data else user

    if not user:
        raise HTTPException(status_code=403, detail="Usuario nao encontrado e criacao automatica desabilitada")

    token = create_access_token(user["id"], user["role"])
    return RedirectResponse(url=f"{redirect_url}?token={token}", status_code=302)


@router.get("/lti/config.xml", tags=["LTI"], response_class=Response)
async def lti_config_xml(request: Request):
    settings = get_settings()
    base = str(request.base_url).rstrip("/")
    xml = generate_lti_config_xml(
        tool_name="Harven.ai",
        launch_url=f"{base}/lti/launch",
        description=(
            "Harven.ai e uma plataforma educacional com IA que utiliza o metodo socratico "
            "para guiar o aprendizado dos alunos atraves de perguntas e reflexoes."
        ),
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/lti/status", tags=["LTI"])
async def lti_status():
    enabled = os.getenv("LTI_ENABLED", "false").lower() == "true"
    configured = bool(os.getenv("LTI_CONSUMER_KEY")) and bool(os.getenv("LTI_SHARED_SECRET"))
    redirect = os.getenv("LTI_REDIRECT_URL") if enabled else None
    return {"enabled": enabled, "configured": configured, "redirect_url": redirect}


# ===================================================================
# UPLOAD ENDPOINTS
# ===================================================================


@router.post("/upload", tags=["Upload"])
async def upload_file(
    file: UploadFile = File(...),
    # P2: this generic upload accepted ANY authenticated user — a student could
    # park arbitrary (allowed-type) files on the server's public /uploads mount.
    # Uploading content is an authoring capability: staff only. File TYPE is
    # validated inside storage.save_file (ValueError → 400 below).
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
):
    try:
        storage = get_storage_service()
        url = await storage.save_file(file, subdir="general")
        return {"url": url, "filename": file.filename}
    except ValueError as e:
        logger.warning(f"Upload validation error: {e}")
        raise HTTPException(status_code=400, detail=f"Tipo de arquivo nao permitido: {file.filename or 'desconhecido'}. Formatos aceitos: pdf, doc, docx, txt, pptx, mp4, jpg, png, etc.")
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload")


@router.post("/upload/video", tags=["Upload"])
async def upload_video(
    file: UploadFile = File(...),
    # P2: same staff-only gate as the generic /upload (authoring capability).
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("mp4", "mov", "avi", "webm"):
        raise HTTPException(status_code=400, detail="Formato de video nao suportado")
    try:
        storage = get_storage_service()
        url = await storage.save_file(file, subdir="videos")
        return {"url": url, "filename": file.filename}
    except ValueError as e:
        logger.error(f"Video upload validation error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Tipo de arquivo nao permitido. Formatos aceitos: mp4, mov, avi, webm.")
    except Exception as e:
        logger.error(f"Video upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload do video")


@router.post("/upload/audio", tags=["Upload"])
async def upload_audio(
    file: UploadFile = File(...),
    # P2: same staff-only gate as the generic /upload (authoring capability).
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "wav", "ogg", "m4a"):
        raise HTTPException(status_code=400, detail="Formato de audio nao suportado")
    try:
        storage = get_storage_service()
        url = await storage.save_file(file, subdir="audio")
        return {"url": url, "filename": file.filename}
    except ValueError as e:
        logger.error(f"Audio upload validation error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Tipo de arquivo nao permitido. Formatos aceitos: mp3, wav, ogg, m4a.")
    except Exception as e:
        logger.error(f"Audio upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload do audio")
