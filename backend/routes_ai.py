"""Routes — AI, Chat Sessions, Integrations, LTI, Uploads."""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from supabase import Client

from auth import create_access_token, get_current_user, require_role
from config import get_settings
from database import get_supabase
from services.ai_service import AIService, AIServiceError, sanitize_ai_error
from services.integration_service import (
    IntegrationService,
    LTIValidationError,
    generate_lti_config_xml,
    validate_lti_launch,
)
from services.storage_service import StorageService

logger = logging.getLogger(__name__)

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


class SocraticDialogueRequest(BaseModel):
    student_message: str = Field(..., min_length=1, max_length=5000)
    chapter_content: str = Field(..., max_length=50000)
    initial_question: dict
    conversation_history: Optional[List[dict]] = []
    interactions_remaining: Optional[int] = Field(3, ge=0, le=20)
    session_id: Optional[str] = None
    chapter_id: Optional[str] = None


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


class ChatSessionCreate(BaseModel):
    user_id: str
    content_id: str
    chapter_id: Optional[str] = None
    course_id: Optional[str] = None


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
    current_user: dict = Depends(get_current_user),
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
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/creator/suggest-chapters", tags=["AI"])
async def ai_suggest_chapters(
    req: QuestionGenerationRequest,
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    try:
        return await get_ai_service().socratic_dialogue(
            student_message=req.student_message,
            chapter_content=req.chapter_content,
            initial_question=req.initial_question,
            conversation_history=req.conversation_history,
            interactions_remaining=req.interactions_remaining or 3,
            session_id=req.session_id,
            user_id=current_user["id"],
            db=client,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Socrates error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/analyst/detect", tags=["AI"])
async def ai_analyst_detect(
    req: AIDetectionRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await get_ai_service().detect_ai_content(
            text=req.text,
            context=req.context,
            interaction_metadata=req.interaction_metadata,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Analyst error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/editor/edit", tags=["AI"])
async def ai_editor_edit(
    req: EditResponseRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await get_ai_service().edit_response(
            orientador_response=req.orientador_response,
            context=req.context,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Editor error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/tester/validate", tags=["AI"])
async def ai_tester_validate(
    req: ValidateResponseRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await get_ai_service().validate_response(
            edited_response=req.edited_response,
            context=req.context,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Tester error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/organizer/session", tags=["AI"])
async def ai_organizer_session(
    req: OrganizeSessionRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await get_ai_service().organize_session(
            action=req.action,
            payload=req.payload,
            metadata=req.metadata,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Organizer error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/organizer/prepare-export", tags=["AI"])
async def ai_organizer_prepare_export(
    session_data: dict,
    current_user: dict = Depends(get_current_user),
):
    try:
        return get_ai_service().prepare_moodle_export(session_data)
    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.get("/api/ai/estimate-cost", tags=["AI"])
async def ai_estimate_cost(
    prompt_tokens: int = Query(0, ge=0),
    completion_tokens: int = Query(0, ge=0),
    model: str = Query(""),
):
    svc = get_ai_service()
    return {
        "estimated_cost_usd": svc.estimate_cost(prompt_tokens, completion_tokens, model),
        "model": model or svc.model,
    }


# ===================================================================
# TTS ENDPOINTS (stubs — real implementation depends on provider)
# ===================================================================


@router.get("/api/ai/tts/voices", tags=["AI - TTS"])
async def tts_voices():
    return {
        "voices": [
            {"id": "alloy", "name": "Alloy", "gender": "neutral"},
            {"id": "echo", "name": "Echo", "gender": "male"},
            {"id": "fable", "name": "Fable", "gender": "female"},
            {"id": "onyx", "name": "Onyx", "gender": "male"},
            {"id": "nova", "name": "Nova", "gender": "female"},
            {"id": "shimmer", "name": "Shimmer", "gender": "female"},
        ]
    }


VALID_TTS_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


class TTSGenerateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    voice: str = Field("alloy", max_length=20)


@router.post("/api/ai/tts/generate", tags=["AI - TTS"])
async def tts_generate(
    body: TTSGenerateRequest,
    current_user: dict = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
):
    svc = get_ai_service()
    if svc.mock_mode or svc.client is None:
        raise HTTPException(
            status_code=503,
            detail="TTS indisponivel: OPENAI_API_KEY nao configurada ou em mock mode.",
        )

    voice = body.voice if body.voice in VALID_TTS_VOICES else "alloy"

    try:
        response = svc.client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=body.text,
        )
        audio_bytes = response.content
    except Exception as e:
        logger.error(f"TTS generate failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Falha na chamada OpenAI TTS: {sanitize_ai_error(e)}")

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
        "voice": voice,
        "model": "tts-1",
        "size_bytes": len(audio_bytes),
    }


@router.get("/api/ai/tts/status", tags=["AI - TTS"])
async def tts_status():
    svc = get_ai_service()
    enabled = svc.client is not None and not svc.mock_mode
    return {
        "enabled": enabled,
        "provider": "openai" if enabled else None,
        "model": "tts-1" if enabled else None,
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

    try:
        result = svc.client.audio.transcriptions.create(
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


@router.post("/chat-sessions", tags=["Chat Sessions"])
async def create_or_get_chat_session(
    data: ChatSessionCreate,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = client.table("chat_sessions").select("*").eq(
            "user_id", data.user_id
        ).eq(
            "content_id", data.content_id
        ).maybe_single().execute()

        existing = result.data

        if existing:
            if existing.get("status") in ("abandoned", "completed"):
                updated = client.table("chat_sessions").update(
                    {"status": "active"}
                ).eq("id", existing["id"]).execute()
                return updated.data[0] if updated.data else existing
            return existing

        new_session = {
            "user_id": data.user_id,
            "content_id": data.content_id,
            "status": "active",
            "total_messages": 0,
        }
        insert_result = client.table("chat_sessions").insert(new_session).execute()
        return insert_result.data[0] if insert_result.data else new_session
    except Exception as e:
        logger.error(f"create_or_get_chat_session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.get("/chat-sessions/{session_id}", tags=["Chat Sessions"])
async def get_chat_session(
    session_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    result = client.table("chat_sessions").select("*").eq(
        "id", session_id
    ).maybe_single().execute()

    session = result.data
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    messages_result = client.table("chat_messages").select("*").eq(
        "session_id", session_id
    ).order("created_at").execute()

    session["messages"] = messages_result.data or []
    return session


@router.get("/chat-sessions/{session_id}/messages", tags=["Chat Sessions"])
async def get_session_messages(
    session_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    result = client.table("chat_messages").select("*").eq(
        "session_id", session_id
    ).order("created_at").execute()
    return result.data or []


@router.post("/chat-sessions/{session_id}/messages", tags=["Chat Sessions"])
async def add_session_message(
    session_id: str,
    data: ChatMessageCreate,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    # Verify session exists
    session_result = client.table("chat_sessions").select("id, total_messages").eq(
        "id", session_id
    ).maybe_single().execute()

    session = session_result.data
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    new_message = {
        "session_id": session_id,
        "role": data.role,
        "content": data.content,
        "agent_type": data.agent_type,
        "metadata": data.metadata,
    }

    try:
        msg_result = client.table("chat_messages").insert(new_message).execute()

        new_count = (session.get("total_messages") or 0) + 1
        client.table("chat_sessions").update(
            {"total_messages": new_count}
        ).eq("id", session_id).execute()

        return msg_result.data[0] if msg_result.data else new_message
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao salvar mensagem")


@router.get("/chat-sessions/by-content/{content_id}", tags=["Chat Sessions"])
async def get_session_by_content(
    content_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    result = client.table("chat_sessions").select("*").eq(
        "content_id", content_id
    ).eq(
        "user_id", current_user["id"]
    ).maybe_single().execute()

    session = result.data
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada para este conteudo")
    return session


@router.get("/users/{user_id}/chat-sessions", tags=["Chat Sessions"])
async def get_user_chat_sessions(
    user_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    result = client.table("chat_sessions").select("*").eq(
        "user_id", user_id
    ).order("created_at", desc=True).execute()
    return result.data or []


@router.put("/chat-sessions/{session_id}/complete", tags=["Chat Sessions"])
async def complete_chat_session(
    session_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    result = client.table("chat_sessions").select("id").eq(
        "id", session_id
    ).maybe_single().execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    updated = client.table("chat_sessions").update(
        {"status": "completed"}
    ).eq("id", session_id).execute()

    return updated.data[0] if updated.data else {"id": session_id, "status": "completed"}


@router.post("/chat-sessions/{session_id}/export-moodle", tags=["Chat Sessions"])
async def export_session_moodle(
    session_id: str,
    client: Client = Depends(get_supabase),
    current_user: dict = Depends(get_current_user),
):
    session_result = client.table("chat_sessions").select("*").eq(
        "id", session_id
    ).maybe_single().execute()

    session = session_result.data
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    messages_result = client.table("chat_messages").select("*").eq(
        "session_id", session_id
    ).order("created_at").execute()

    session["messages"] = messages_result.data or []
    session["session_id"] = session["id"]

    # Fetch user info for export
    user_result = client.table("users").select("name, email").eq(
        "id", session.get("user_id", "")
    ).maybe_single().execute()

    user_data = user_result.data
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


@router.post("/integrations/moodle/webhook", tags=["Integrations - Moodle"])
async def moodle_webhook(
    request: Request,
    svc: IntegrationService = Depends(get_integration_service),
):
    try:
        body = await request.json()
    except Exception:
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

    auto_create = os.getenv("LTI_AUTO_CREATE_USERS", "true").lower() == "true"
    if not user and auto_create:
        from auth import hash_password
        new_user = {
            "ra": launch_data.ra or f"lti-{launch_data.user_id}",
            "name": launch_data.name or "LTI User",
            "email": launch_data.email,
            "role": launch_data.role,
            "password_hash": hash_password(launch_data.ra or launch_data.user_id),
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
    current_user: dict = Depends(get_current_user),
):
    try:
        storage = get_storage_service()
        url = await storage.save_file(file, subdir="general")
        return {"url": url, "filename": file.filename}
    except ValueError as e:
        logger.error(f"Upload validation error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Invalid request")
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload")


@router.post("/upload/video", tags=["Upload"])
async def upload_video(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
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
        raise HTTPException(status_code=400, detail="Invalid request")
    except Exception as e:
        logger.error(f"Video upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload do video")


@router.post("/upload/audio", tags=["Upload"])
async def upload_audio(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
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
        raise HTTPException(status_code=400, detail="Invalid request")
    except Exception as e:
        logger.error(f"Audio upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload do audio")
