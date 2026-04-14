"""Routes — AI, Chat Sessions, Integrations, LTI, Uploads."""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from auth import create_access_token, get_current_user, require_role
from config import get_settings
from database import get_db
from models.chat import ChatMessage, ChatSession
from models.user import User
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


def get_integration_service(db: Session = Depends(get_db)) -> IntegrationService:
    settings = get_settings()
    return IntegrationService(db, {
        "jacad_base_url": os.getenv("JACAD_BASE_URL", ""),
        "jacad_api_key": os.getenv("JACAD_API_KEY", ""),
        "moodle_url": os.getenv("MOODLE_URL", ""),
        "moodle_token": os.getenv("MOODLE_TOKEN", ""),
    })


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class QuestionGenerationRequest(BaseModel):
    chapter_content: str = Field(..., min_length=10, max_length=50000)
    chapter_title: Optional[str] = Field(None, max_length=300)
    learning_objective: Optional[str] = Field(None, max_length=1000)
    difficulty: Optional[str] = Field("intermediario", max_length=30)
    max_questions: Optional[int] = Field(3, ge=1, le=10)


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await get_ai_service().generate_questions(
            chapter_content=req.chapter_content,
            chapter_title=req.chapter_title or "",
            learning_objective=req.learning_objective or "",
            difficulty=req.difficulty or "intermediario",
            max_questions=req.max_questions or 3,
            user_id=current_user.id,
            db=db,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Creator error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/socrates/dialogue", tags=["AI"])
async def ai_socrates_dialogue(
    req: SocraticDialogueRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await get_ai_service().socratic_dialogue(
            student_message=req.student_message,
            chapter_content=req.chapter_content,
            initial_question=req.initial_question,
            conversation_history=req.conversation_history,
            interactions_remaining=req.interactions_remaining or 3,
            session_id=req.session_id,
            user_id=current_user.id,
            db=db,
        )
    except AIServiceError as e:
        raise HTTPException(status_code=503, detail=sanitize_ai_error(e))
    except Exception as e:
        logger.error(f"Socrates error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/api/ai/analyst/detect", tags=["AI"])
async def ai_analyst_detect(
    req: AIDetectionRequest,
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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


@router.post("/api/ai/tts/generate", tags=["AI - TTS"])
async def tts_generate(
    text: str = "",
    voice: str = "alloy",
    current_user: User = Depends(get_current_user),
):
    return {"status": "mock", "message": "TTS nao configurado — retornando stub", "audio_url": None}


@router.get("/api/ai/tts/status", tags=["AI - TTS"])
async def tts_status():
    return {"enabled": False, "provider": None}


@router.post("/api/ai/transcribe", tags=["AI - TTS"])
async def ai_transcribe(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    return {"status": "mock", "text": "", "message": "Transcricao nao configurada"}


# ===================================================================
# CHAT SESSION ENDPOINTS
# ===================================================================


def _session_to_dict(session: ChatSession) -> Dict[str, Any]:
    d: Dict[str, Any] = {}
    for c in ChatSession.__table__.columns:
        val = getattr(session, c.key, None)
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        d[c.name] = val
    return d


def _message_to_dict(msg: ChatMessage) -> Dict[str, Any]:
    return {
        "id": msg.id,
        "session_id": msg.session_id,
        "role": msg.role,
        "content": msg.content,
        "agent_type": msg.agent_type,
        "metadata": msg.metadata_,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.post("/chat-sessions", tags=["Chat Sessions"])
async def create_or_get_chat_session(
    data: ChatSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        existing = db.query(ChatSession).filter(
            ChatSession.user_id == data.user_id,
            ChatSession.content_id == data.content_id,
        ).first()

        if existing:
            if existing.status in ("abandoned", "completed"):
                existing.status = "active"
                db.commit()
                db.refresh(existing)
            return _session_to_dict(existing)

        session = ChatSession(
            user_id=data.user_id,
            content_id=data.content_id,
            status="active",
            total_messages=0,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return _session_to_dict(session)
    except Exception as e:
        db.rollback()
        logger.error(f"create_or_get_chat_session error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.get("/chat-sessions/{session_id}", tags=["Chat Sessions"])
async def get_chat_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = db.query(ChatSession).options(joinedload(ChatSession.messages)).filter(
        ChatSession.id == session_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    d = _session_to_dict(session)
    d["messages"] = [_message_to_dict(m) for m in session.messages]
    return d


@router.get("/chat-sessions/{session_id}/messages", tags=["Chat Sessions"])
async def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
    ).order_by(ChatMessage.created_at).all()
    return [_message_to_dict(m) for m in messages]


@router.post("/chat-sessions/{session_id}/messages", tags=["Chat Sessions"])
async def add_session_message(
    session_id: str,
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    msg = ChatMessage(
        session_id=session_id,
        role=data.role,
        content=data.content,
        agent_type=data.agent_type,
        metadata_=data.metadata,
    )
    db.add(msg)
    session.total_messages = (session.total_messages or 0) + 1
    try:
        db.commit()
        db.refresh(msg)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Erro ao salvar mensagem")
    return _message_to_dict(msg)


@router.get("/chat-sessions/by-content/{content_id}", tags=["Chat Sessions"])
async def get_session_by_content(
    content_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = db.query(ChatSession).filter(
        ChatSession.content_id == content_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada para este conteudo")
    return _session_to_dict(session)


@router.get("/users/{user_id}/chat-sessions", tags=["Chat Sessions"])
async def get_user_chat_sessions(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions = db.query(ChatSession).filter(
        ChatSession.user_id == user_id,
    ).order_by(ChatSession.created_at.desc()).all()
    return [_session_to_dict(s) for s in sessions]


@router.put("/chat-sessions/{session_id}/complete", tags=["Chat Sessions"])
async def complete_chat_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    session.status = "completed"
    db.commit()
    db.refresh(session)
    return _session_to_dict(session)


@router.post("/chat-sessions/{session_id}/export-moodle", tags=["Chat Sessions"])
async def export_session_moodle(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = db.query(ChatSession).options(joinedload(ChatSession.messages)).filter(
        ChatSession.id == session_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    session_data = _session_to_dict(session)
    session_data["messages"] = [_message_to_dict(m) for m in session.messages]
    session_data["session_id"] = session.id
    session_data["user_name"] = session.user.name if session.user else ""
    session_data["user_email"] = session.user.email if session.user else ""

    svc = get_ai_service()
    return svc.prepare_moodle_export(session_data)


# ===================================================================
# INTEGRATION ENDPOINTS
# ===================================================================


@router.post("/integrations/test-connection", tags=["Integrations"])
async def integration_test_connection(
    system: str = Query(...),
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN", "TEACHER")),
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
    current_user: User = Depends(require_role("ADMIN")),
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
    current_user: User = Depends(require_role("ADMIN")),
):
    return await svc.get_mappings(entity_type)


# ---- JACAD ----

@router.post("/integrations/jacad/sync", tags=["Integrations - JACAD"])
async def jacad_sync(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN")),
):
    users_result = await svc.sync_users_from_jacad()
    disc_result = await svc.sync_disciplines_from_jacad()
    return {"users": users_result.to_dict(), "disciplines": disc_result.to_dict()}


@router.post("/integrations/jacad/import-students", tags=["Integrations - JACAD"])
async def jacad_import_students(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN")),
):
    result = await svc.sync_users_from_jacad()
    return result.to_dict()


@router.post("/integrations/jacad/import-disciplines", tags=["Integrations - JACAD"])
async def jacad_import_disciplines(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN")),
):
    result = await svc.sync_disciplines_from_jacad()
    return result.to_dict()


@router.get("/integrations/jacad/student/{ra}", tags=["Integrations - JACAD"])
async def jacad_student(
    ra: str,
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN", "TEACHER")),
):
    student = await svc.get_jacad_student(ra)
    if not student:
        raise HTTPException(status_code=404, detail="Aluno nao encontrado no JACAD")
    return student


# ---- Moodle ----

@router.post("/integrations/moodle/sync", tags=["Integrations - Moodle"])
async def moodle_sync(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN")),
):
    export_result = await svc.export_sessions_to_moodle()
    import_result = await svc.import_ratings_from_moodle()
    return {"export": export_result.to_dict(), "import": import_result.to_dict()}


@router.post("/integrations/moodle/import-users", tags=["Integrations - Moodle"])
async def moodle_import_users(
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN")),
):
    return {"status": "not_implemented", "message": "Import de usuarios via Moodle nao implementado"}


@router.post("/integrations/moodle/export-sessions", tags=["Integrations - Moodle"])
async def moodle_export_sessions(
    filters: Optional[dict] = None,
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN", "TEACHER")),
):
    result = await svc.export_sessions_to_moodle(filters)
    return result.to_dict()


@router.get("/integrations/moodle/ratings", tags=["Integrations - Moodle"])
async def moodle_ratings(
    session_id: Optional[str] = None,
    svc: IntegrationService = Depends(get_integration_service),
    current_user: User = Depends(require_role("ADMIN", "TEACHER")),
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
    db: Session = Depends(get_db),
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
        raise HTTPException(status_code=401, detail=str(e))

    # Find or create user
    user = None
    if launch_data.ra:
        user = db.query(User).filter(User.ra == launch_data.ra).first()
    if not user and launch_data.email:
        user = db.query(User).filter(User.email == launch_data.email).first()

    auto_create = os.getenv("LTI_AUTO_CREATE_USERS", "true").lower() == "true"
    if not user and auto_create:
        from auth import hash_password
        user = User(
            ra=launch_data.ra or f"lti-{launch_data.user_id}",
            name=launch_data.name or "LTI User",
            email=launch_data.email,
            role=launch_data.role,
            password_hash=hash_password(launch_data.ra or launch_data.user_id),
            moodle_user_id=launch_data.user_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif user:
        if launch_data.name and user.name != launch_data.name:
            user.name = launch_data.name
        if not user.moodle_user_id:
            user.moodle_user_id = launch_data.user_id
        db.commit()

    if not user:
        raise HTTPException(status_code=403, detail="Usuario nao encontrado e criacao automatica desabilitada")

    token = create_access_token(user.id, user.role)
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
    current_user: User = Depends(get_current_user),
):
    try:
        storage = get_storage_service()
        url = await storage.save_file(file, subdir="general")
        return {"url": url, "filename": file.filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload")


@router.post("/upload/video", tags=["Upload"])
async def upload_video(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("mp4", "mov", "avi", "webm"):
        raise HTTPException(status_code=400, detail="Formato de video nao suportado")
    try:
        storage = get_storage_service()
        url = await storage.save_file(file, subdir="videos")
        return {"url": url, "filename": file.filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Video upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload do video")


@router.post("/upload/audio", tags=["Upload"])
async def upload_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("mp3", "wav", "ogg", "m4a"):
        raise HTTPException(status_code=400, detail="Formato de audio nao suportado")
    try:
        storage = get_storage_service()
        url = await storage.save_file(file, subdir="audio")
        return {"url": url, "filename": file.filename}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Audio upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao fazer upload do audio")
