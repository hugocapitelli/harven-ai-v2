"""
Harven AI v2 — Admin, Notifications, Search, Dashboard & Gamification routes.
APIRouter to be included in main.py via: app.include_router(routes_admin.router)
"""

import csv
import io
import json
import logging
import os
import re
import secrets
import shutil
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from auth import get_current_user, require_role
from config import get_settings
from database import get_db
from models.chat import ChatMessage, ChatSession
from models.course import Chapter, Content, Course
from models.discipline import Discipline, DisciplineStudent, DisciplineTeacher
from models.gamification import Certificate, CourseProgress, UserAchievement, UserActivity, UserStats
from models.integration import SessionReview
from models.notification import Notification
from models.settings import SystemBackup, SystemLog, SystemSettings
from models.user import User

router = APIRouter()
logger = logging.getLogger("harven")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SENSITIVE_FIELDS = {
    "openai_key",
    "moodle_token",
    "smtp_password",
    "jacad_api_key",
    "moodle_webhook_secret",
    "lti_shared_secret",
}

PUBLIC_SETTINGS_FIELDS = {
    "platform_name",
    "primary_color",
    "logo_url",
    "login_logo_url",
    "login_bg_url",
    "ai_tutor_enabled",
    "gamification_enabled",
    "dark_mode_enabled",
}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class NotificationCreate(BaseModel):
    user_id: str
    title: str = Field(..., min_length=1, max_length=255)
    message: Optional[str] = None
    notification_type: Optional[str] = Field(None, max_length=50)
    link: Optional[str] = Field(None, max_length=500)


class ActivityCreate(BaseModel):
    activity_type: str = Field(..., max_length=50)
    description: Optional[str] = None
    points: int = 0
    metadata_: Optional[dict] = Field(None, alias="metadata")


class SessionReviewCreate(BaseModel):
    rating: Optional[float] = Field(None, ge=0, le=10)
    feedback: Optional[str] = None


class SessionReviewReply(BaseModel):
    reply: str = Field(..., min_length=1)


class CertificateCreate(BaseModel):
    course_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_to_dict(row: SystemSettings) -> dict:
    """Convert a SystemSettings ORM row to a plain dict (excluding internal SA state)."""
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _mask_sensitive(data: dict) -> dict:
    """Mask sensitive fields: show first 4 chars + ****."""
    out = dict(data)
    for key in SENSITIVE_FIELDS:
        val = out.get(key)
        if val and isinstance(val, str) and len(val) > 4:
            out[key] = val[:4] + "****"
        elif val:
            out[key] = "****"
    return out


def _sanitize_search(q: str) -> str:
    """Remove SQL wildcards and special chars, cap length."""
    sanitized = re.sub(r"[%_\\'\";]", "", q.strip())
    return sanitized[:200]


def _get_or_create_settings(db: Session) -> SystemSettings:
    """Return the single settings row or create one if missing."""
    row = db.query(SystemSettings).first()
    if row is None:
        row = SystemSettings(id=str(uuid4()), platform_name="Harven.AI")
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _log(db: Session, message: str, author: str = "system", log_type: str = "info", st: str = "ok"):
    """Append a row to system_logs."""
    db.add(SystemLog(id=str(uuid4()), message=message, author=author, log_type=log_type, status=st))
    db.commit()


def _save_upload(upload: UploadFile, subfolder: str) -> str:
    """Save an UploadFile to UPLOAD_DIR/<subfolder>/ and return the public URL."""
    settings = get_settings()
    base = settings.UPLOAD_DIR
    dest_dir = os.path.join(base, subfolder)
    os.makedirs(dest_dir, exist_ok=True)

    ext = os.path.splitext(upload.filename or "img.png")[1]
    fname = f"{uuid4().hex[:12]}{ext}"
    dest = os.path.join(dest_dir, fname)

    upload.file.seek(0)
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)

    return f"/uploads/{subfolder}/{fname}"


def _validate_image(upload: UploadFile):
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo de arquivo invalido: {upload.content_type}")
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    if size > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Imagem excede 5 MB")


# ═══════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/settings/public", tags=["Settings"], summary="Configuracoes publicas")
async def get_public_settings(db: Session = Depends(get_db)):
    """Returns public-facing settings (no auth required)."""
    row = _get_or_create_settings(db)
    data = _settings_to_dict(row)
    return {k: v for k, v in data.items() if k in PUBLIC_SETTINGS_FIELDS}


@router.get("/admin/settings", tags=["Admin Settings"], summary="Todas as configuracoes (admin)")
async def get_admin_settings(
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    row = _get_or_create_settings(db)
    return _mask_sensitive(_settings_to_dict(row))


@router.post("/admin/settings", tags=["Admin Settings"], summary="Salvar configuracoes (admin)")
async def save_admin_settings(
    payload: dict,
    admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    row = _get_or_create_settings(db)

    # Filter out empty-string URL fields so they aren't overwritten to ""
    url_fields = {c.name for c in row.__table__.columns if c.name.endswith("_url")}
    cleaned = {k: v for k, v in payload.items() if not (k in url_fields and v == "")}

    # Never accept raw sensitive fields that look like masked values
    for key in SENSITIVE_FIELDS:
        val = cleaned.get(key)
        if isinstance(val, str) and val.endswith("****"):
            cleaned.pop(key, None)

    for key, val in cleaned.items():
        if hasattr(row, key) and key not in ("id", "created_at", "updated_at"):
            setattr(row, key, val)

    db.commit()
    db.refresh(row)
    _log(db, f"Settings atualizadas por {admin.name}", author=admin.name, log_type="settings")
    return _mask_sensitive(_settings_to_dict(row))


@router.post("/admin/settings/upload-logo", tags=["Admin Settings"], summary="Upload logo principal")
async def upload_logo(
    file: UploadFile = File(...),
    admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    _validate_image(file)
    url = _save_upload(file, "logos")
    row = _get_or_create_settings(db)
    row.logo_url = url
    db.commit()
    _log(db, f"Logo atualizado por {admin.name}", author=admin.name, log_type="settings")
    return {"logo_url": url}


@router.post("/admin/settings/upload-login-logo", tags=["Admin Settings"], summary="Upload logo do login")
async def upload_login_logo(
    file: UploadFile = File(...),
    admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    _validate_image(file)
    url = _save_upload(file, "logos")
    row = _get_or_create_settings(db)
    row.login_logo_url = url
    db.commit()
    _log(db, f"Login logo atualizado por {admin.name}", author=admin.name, log_type="settings")
    return {"login_logo_url": url}


@router.post("/admin/settings/upload-login-bg", tags=["Admin Settings"], summary="Upload background do login")
async def upload_login_bg(
    file: UploadFile = File(...),
    admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    _validate_image(file)
    url = _save_upload(file, "backgrounds")
    row = _get_or_create_settings(db)
    row.login_bg_url = url
    db.commit()
    _log(db, f"Login background atualizado por {admin.name}", author=admin.name, log_type="settings")
    return {"login_bg_url": url}


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN MONITORING
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/admin/stats", tags=["Admin Monitoring"], summary="Estatisticas gerais")
async def admin_stats(
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    users_total = db.query(func.count(User.id)).scalar() or 0
    users_by_role = dict(
        db.query(User.role, func.count(User.id)).group_by(User.role).all()
    )
    courses_total = db.query(func.count(Course.id)).scalar() or 0
    disciplines_total = db.query(func.count(Discipline.id)).scalar() or 0
    sessions_total = db.query(func.count(ChatSession.id)).scalar() or 0
    messages_total = db.query(func.count(ChatMessage.id)).scalar() or 0
    notifications_total = db.query(func.count(Notification.id)).scalar() or 0

    return {
        "users": {"total": users_total, "by_role": users_by_role},
        "courses": courses_total,
        "disciplines": disciplines_total,
        "chat_sessions": sessions_total,
        "messages": messages_total,
        "notifications": notifications_total,
    }


@router.get("/admin/performance", tags=["Admin Monitoring"], summary="Metricas de performance")
async def admin_performance(
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    avg_score = db.query(func.avg(ChatSession.performance_score)).filter(
        ChatSession.performance_score.isnot(None)
    ).scalar()
    avg_messages = db.query(func.avg(ChatSession.total_messages)).scalar()
    active_sessions = db.query(func.count(ChatSession.id)).filter(
        ChatSession.status == "active"
    ).scalar() or 0

    return {
        "avg_performance_score": round(float(avg_score or 0), 2),
        "avg_messages_per_session": round(float(avg_messages or 0), 1),
        "active_sessions": active_sessions,
    }


@router.get("/admin/storage", tags=["Admin Monitoring"], summary="Uso de armazenamento")
async def admin_storage(
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    upload_dir = settings.UPLOAD_DIR
    total_size = 0
    file_count = 0
    if os.path.isdir(upload_dir):
        for dirpath, _dirs, filenames in os.walk(upload_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
                file_count += 1

    return {
        "upload_dir": upload_dir,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "file_count": file_count,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN LOGS
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/admin/logs", tags=["Admin Logs"], summary="Logs paginados")
async def get_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    log_type: Optional[str] = None,
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    q = db.query(SystemLog)
    if log_type:
        q = q.filter(SystemLog.log_type == log_type)
    total = q.count()
    rows = q.order_by(SystemLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "data": [
            {
                "id": r.id,
                "message": r.message,
                "author": r.author,
                "status": r.status,
                "log_type": r.log_type,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": total > page * per_page,
    }


@router.get("/admin/logs/search", tags=["Admin Logs"], summary="Buscar logs")
async def search_logs(
    q: str = Query("", max_length=200),
    log_type: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    query = db.query(SystemLog)
    if q:
        safe = _sanitize_search(q)
        query = query.filter(
            or_(
                SystemLog.message.ilike(f"%{safe}%"),
                SystemLog.author.ilike(f"%{safe}%"),
            )
        )
    if log_type:
        query = query.filter(SystemLog.log_type == log_type)
    if status_filter:
        query = query.filter(SystemLog.status == status_filter)

    total = query.count()
    rows = query.order_by(SystemLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "data": [
            {
                "id": r.id,
                "message": r.message,
                "author": r.author,
                "status": r.status,
                "log_type": r.log_type,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/admin/logs/export", tags=["Admin Logs"], summary="Exportar logs")
async def export_logs(
    fmt: str = Query("json", regex="^(json|csv)$"),
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    from fastapi.responses import StreamingResponse

    rows = db.query(SystemLog).order_by(SystemLog.created_at.desc()).limit(5000).all()

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "message", "author", "status", "log_type", "created_at"])
        for r in rows:
            writer.writerow([r.id, r.message, r.author, r.status, r.log_type, r.created_at])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=logs.csv"},
        )

    data = [
        {
            "id": r.id,
            "message": r.message,
            "author": r.author,
            "status": r.status,
            "log_type": r.log_type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return StreamingResponse(
        iter([json.dumps(data, ensure_ascii=False, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=logs.json"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN BACKUPS
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/admin/backups", tags=["Admin Backups"], summary="Listar backups")
async def list_backups(
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    rows = db.query(SystemBackup).order_by(SystemBackup.created_at.desc()).all()
    return {
        "data": [
            {
                "id": r.id,
                "filename": r.filename,
                "size": r.size,
                "records_count": r.records_count,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("/admin/backups", tags=["Admin Backups"], summary="Criar backup", status_code=201)
async def create_backup(
    admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    backup_dir = os.path.join(settings.UPLOAD_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{ts}.json"
    filepath = os.path.join(backup_dir, filename)

    # Collect counts per table
    counts = {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "courses": db.query(func.count(Course.id)).scalar() or 0,
        "disciplines": db.query(func.count(Discipline.id)).scalar() or 0,
        "chat_sessions": db.query(func.count(ChatSession.id)).scalar() or 0,
    }
    total_records = sum(counts.values())

    # Write metadata file (actual DB dump would be done by a dedicated job)
    meta = {"created_at": ts, "tables": counts, "total_records": total_records}
    with open(filepath, "w") as f:
        json.dump(meta, f, indent=2)

    fsize = os.path.getsize(filepath)
    row = SystemBackup(
        id=str(uuid4()),
        filename=filename,
        size=fsize,
        records_count=total_records,
        status="completed",
        storage_path=filepath,
    )
    db.add(row)
    db.commit()

    _log(db, f"Backup criado: {filename}", author=admin.name, log_type="backup")

    return {
        "id": row.id,
        "filename": filename,
        "size": fsize,
        "records_count": total_records,
        "status": "completed",
    }


@router.get("/admin/backups/{backup_id}/download", tags=["Admin Backups"], summary="Download backup")
async def download_backup(
    backup_id: str,
    _admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    from fastapi.responses import FileResponse

    row = db.query(SystemBackup).filter(SystemBackup.id == backup_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Backup nao encontrado")
    if not row.storage_path or not os.path.isfile(row.storage_path):
        raise HTTPException(status_code=404, detail="Arquivo de backup nao encontrado no disco")
    return FileResponse(row.storage_path, filename=row.filename, media_type="application/json")


@router.delete("/admin/backups/{backup_id}", tags=["Admin Backups"], summary="Excluir backup")
async def delete_backup(
    backup_id: str,
    admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    row = db.query(SystemBackup).filter(SystemBackup.id == backup_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Backup nao encontrado")
    if row.storage_path and os.path.isfile(row.storage_path):
        os.remove(row.storage_path)
    db.delete(row)
    db.commit()
    _log(db, f"Backup excluido: {row.filename}", author=admin.name, log_type="backup")
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN SECURITY
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/admin/force-logout", tags=["Admin Security"], summary="Invalidar todos os tokens")
async def force_logout(
    admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Rotate the JWT secret so every existing token becomes invalid.
    The new secret is written to .env and the settings cache is cleared.
    """
    new_secret = secrets.token_urlsafe(48)

    # Update .env file
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines: list[str] = []
    replaced = False
    if os.path.isfile(env_path):
        with open(env_path) as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith("JWT_SECRET_KEY="):
                lines[i] = f"JWT_SECRET_KEY={new_secret}\n"
                replaced = True
    if not replaced:
        lines.append(f"JWT_SECRET_KEY={new_secret}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)

    # Clear cached settings so next request picks up the new key
    from config import get_settings as _gs
    _gs.cache_clear()

    _log(db, f"Force logout executado por {admin.name}", author=admin.name, log_type="security")
    return {"message": "Todos os tokens foram invalidados. Usuarios deverao fazer login novamente."}


@router.post("/admin/clear-cache", tags=["Admin Security"], summary="Limpar cache interno")
async def clear_cache(
    admin: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    from config import get_settings as _gs
    _gs.cache_clear()
    _log(db, f"Cache limpo por {admin.name}", author=admin.name, log_type="security")
    return {"message": "Cache interno limpo com sucesso."}


# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/notifications/{user_id}/count", tags=["Notifications"], summary="Contagem de nao lidas")
async def notification_count(
    user_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .scalar()
        or 0
    )
    return {"unread": total}


@router.get("/notifications/{user_id}", tags=["Notifications"], summary="Listar notificacoes")
async def list_notifications(
    user_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.user_id == user_id)
    total = q.count()
    rows = q.order_by(Notification.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "data": [
            {
                "id": r.id,
                "title": r.title,
                "message": r.message,
                "type": r.notification_type,
                "link": r.link,
                "read": r.is_read,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": total > page * per_page,
    }


@router.post("/notifications", tags=["Notifications"], summary="Criar notificacao", status_code=201)
async def create_notification(
    body: NotificationCreate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = Notification(
        id=str(uuid4()),
        user_id=body.user_id,
        title=body.title,
        message=body.message,
        notification_type=body.notification_type,
        link=body.link,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "title": row.title,
        "message": row.message,
        "type": row.notification_type,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.put("/notifications/{notification_id}/read", tags=["Notifications"], summary="Marcar como lida")
async def mark_read(
    notification_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(Notification).filter(Notification.id == notification_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada")
    row.is_read = True
    db.commit()
    return {"id": notification_id, "read": True}


@router.put("/notifications/{user_id}/read-all", tags=["Notifications"], summary="Marcar todas como lidas")
async def mark_all_read(
    user_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .update({"is_read": True})
    )
    db.commit()
    return {"marked_read": count}


@router.delete("/notifications/{notification_id}", tags=["Notifications"], summary="Excluir notificacao")
async def delete_notification(
    notification_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(Notification).filter(Notification.id == notification_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada")
    db.delete(row)
    db.commit()
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/search", tags=["Search"], summary="Busca global")
async def global_search(
    q: str = Query(..., min_length=2, max_length=200),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    safe = _sanitize_search(q)
    if len(safe) < 2:
        return {"users": [], "courses": [], "disciplines": []}

    pattern = f"%{safe}%"

    users = (
        db.query(User)
        .filter(or_(User.name.ilike(pattern), User.email.ilike(pattern), User.ra.ilike(pattern)))
        .limit(10)
        .all()
    )
    courses = (
        db.query(Course)
        .filter(or_(Course.title.ilike(pattern), Course.description.ilike(pattern)))
        .limit(10)
        .all()
    )
    disciplines = (
        db.query(Discipline)
        .filter(or_(Discipline.name.ilike(pattern), Discipline.code.ilike(pattern)))
        .limit(10)
        .all()
    )

    return {
        "users": [
            {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "ra": u.ra}
            for u in users
        ],
        "courses": [
            {"id": c.id, "title": c.title, "status": c.status, "discipline_id": c.discipline_id}
            for c in courses
        ],
        "disciplines": [
            {"id": d.id, "name": d.name, "code": d.code}
            for d in disciplines
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/dashboard/stats", tags=["Dashboard"], summary="Estatisticas agregadas")
async def dashboard_stats(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_courses = db.query(func.count(Course.id)).scalar() or 0
    total_disciplines = db.query(func.count(Discipline.id)).scalar() or 0
    total_sessions = db.query(func.count(ChatSession.id)).scalar() or 0
    avg_score = db.query(func.avg(ChatSession.performance_score)).filter(
        ChatSession.performance_score.isnot(None)
    ).scalar()

    return {
        "total_users": total_users,
        "total_courses": total_courses,
        "total_disciplines": total_disciplines,
        "total_sessions": total_sessions,
        "avg_performance_score": round(float(avg_score or 0), 2),
    }


@router.get("/classes/{class_id}/stats", tags=["Dashboard"], summary="Estatisticas de turma")
async def class_stats(
    class_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """class_id maps to a Discipline id."""
    disc = db.query(Discipline).filter(Discipline.id == class_id).first()
    if not disc:
        raise HTTPException(status_code=404, detail="Turma nao encontrada")

    student_count = (
        db.query(func.count(DisciplineStudent.id))
        .filter(DisciplineStudent.discipline_id == class_id)
        .scalar()
        or 0
    )
    course_count = (
        db.query(func.count(Course.id))
        .filter(Course.discipline_id == class_id)
        .scalar()
        or 0
    )
    # Sessions from students in this discipline
    student_ids = (
        db.query(DisciplineStudent.student_id)
        .filter(DisciplineStudent.discipline_id == class_id)
        .subquery()
    )
    session_count = (
        db.query(func.count(ChatSession.id))
        .filter(ChatSession.user_id.in_(student_ids.select()))
        .scalar()
        or 0
    )

    return {
        "discipline_id": class_id,
        "discipline_name": disc.name,
        "student_count": student_count,
        "course_count": course_count,
        "session_count": session_count,
    }


@router.get(
    "/disciplines/{discipline_id}/students/stats",
    tags=["Dashboard"],
    summary="Estatisticas de alunos de disciplina",
)
async def discipline_students_stats(
    discipline_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    disc = db.query(Discipline).filter(Discipline.id == discipline_id).first()
    if not disc:
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")

    rows = (
        db.query(
            User.id,
            User.name,
            User.ra,
            func.count(ChatSession.id).label("sessions"),
            func.avg(ChatSession.performance_score).label("avg_score"),
        )
        .join(DisciplineStudent, DisciplineStudent.student_id == User.id)
        .outerjoin(ChatSession, ChatSession.user_id == User.id)
        .filter(DisciplineStudent.discipline_id == discipline_id)
        .group_by(User.id, User.name, User.ra)
        .all()
    )

    return {
        "discipline_id": discipline_id,
        "discipline_name": disc.name,
        "students": [
            {
                "id": r.id,
                "name": r.name,
                "ra": r.ra,
                "sessions": r.sessions or 0,
                "avg_score": round(float(r.avg_score or 0), 2),
            }
            for r in rows
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# GAMIFICATION
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/users/{user_id}/stats", tags=["Gamification"], summary="Stats do usuario")
async def user_stats(
    user_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserStats).filter(UserStats.user_id == user_id).first()
    if not row:
        return {
            "user_id": user_id,
            "courses_completed": 0,
            "hours_studied": 0.0,
            "average_score": 0.0,
            "streak_days": 0,
            "total_points": 0,
        }
    return {
        "user_id": user_id,
        "courses_completed": row.courses_completed,
        "hours_studied": row.hours_studied,
        "average_score": row.average_score,
        "streak_days": row.streak_days,
        "total_points": row.total_points,
    }


@router.get("/users/{user_id}/activities", tags=["Gamification"], summary="Atividades do usuario")
async def user_activities(
    user_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(UserActivity).filter(UserActivity.user_id == user_id)
    total = q.count()
    rows = q.order_by(UserActivity.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "data": [
            {
                "id": r.id,
                "activity_type": r.activity_type,
                "description": r.description,
                "points": r.points,
                "metadata": r.metadata_,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": total > page * per_page,
    }


@router.post("/users/{user_id}/activities", tags=["Gamification"], summary="Registrar atividade", status_code=201)
async def create_activity(
    user_id: str,
    body: ActivityCreate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = UserActivity(
        id=str(uuid4()),
        user_id=user_id,
        activity_type=body.activity_type,
        description=body.description,
        points=body.points,
        metadata_=body.metadata_,
    )
    db.add(row)

    # Update user stats (upsert)
    stats = db.query(UserStats).filter(UserStats.user_id == user_id).first()
    if not stats:
        stats = UserStats(id=str(uuid4()), user_id=user_id, total_points=0)
        db.add(stats)
    stats.total_points = (stats.total_points or 0) + body.points

    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "activity_type": row.activity_type,
        "points": row.points,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/users/{user_id}/achievements", tags=["Gamification"], summary="Conquistas do usuario")
async def user_achievements(
    user_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(UserAchievement)
        .filter(UserAchievement.user_id == user_id)
        .order_by(UserAchievement.unlocked_at.desc())
        .all()
    )
    return {
        "data": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "icon": r.icon,
                "category": r.category,
                "rarity": r.rarity,
                "points": r.points,
                "unlocked_at": r.unlocked_at.isoformat() if r.unlocked_at else None,
            }
            for r in rows
        ]
    }


@router.post(
    "/users/{user_id}/achievements/{achievement_id}/unlock",
    tags=["Gamification"],
    summary="Desbloquear conquista",
    status_code=201,
)
async def unlock_achievement(
    user_id: str,
    achievement_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Prevent duplicates
    existing = (
        db.query(UserAchievement)
        .filter(UserAchievement.user_id == user_id, UserAchievement.id == achievement_id)
        .first()
    )
    if existing:
        return {
            "id": existing.id,
            "name": existing.name,
            "already_unlocked": True,
        }

    row = UserAchievement(
        id=achievement_id,
        user_id=user_id,
        name=achievement_id,
        unlocked_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "unlocked_at": row.unlocked_at.isoformat()}


@router.get("/users/{user_id}/certificates", tags=["Gamification"], summary="Certificados do usuario")
async def user_certificates(
    user_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Certificate)
        .filter(Certificate.user_id == user_id)
        .order_by(Certificate.issued_at.desc())
        .all()
    )
    return {
        "data": [
            {
                "id": r.id,
                "course_id": r.course_id,
                "certificate_number": r.certificate_number,
                "issued_at": r.issued_at.isoformat() if r.issued_at else None,
            }
            for r in rows
        ]
    }


@router.post("/users/{user_id}/certificates", tags=["Gamification"], summary="Emitir certificado", status_code=201)
async def issue_certificate(
    user_id: str,
    body: CertificateCreate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Prevent duplicate
    existing = (
        db.query(Certificate)
        .filter(Certificate.user_id == user_id, Certificate.course_id == body.course_id)
        .first()
    )
    if existing:
        return {
            "id": existing.id,
            "certificate_number": existing.certificate_number,
            "already_issued": True,
        }

    cert_number = f"HARVEN-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"
    row = Certificate(
        id=str(uuid4()),
        user_id=user_id,
        course_id=body.course_id,
        certificate_number=cert_number,
        issued_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "certificate_number": row.certificate_number,
        "issued_at": row.issued_at.isoformat(),
    }


@router.get(
    "/users/{user_id}/courses/{course_id}/progress",
    tags=["Gamification"],
    summary="Progresso do usuario no curso",
)
async def user_course_progress(
    user_id: str,
    course_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(CourseProgress)
        .filter(CourseProgress.user_id == user_id, CourseProgress.course_id == course_id)
        .first()
    )
    if not row:
        return {
            "user_id": user_id,
            "course_id": course_id,
            "progress_percent": 0.0,
            "completed_contents": 0,
            "total_contents": 0,
        }
    return {
        "user_id": user_id,
        "course_id": course_id,
        "progress_percent": row.progress_percent,
        "completed_contents": row.completed_contents,
        "total_contents": row.total_contents,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post(
    "/users/{user_id}/courses/{course_id}/complete-content/{content_id}",
    tags=["Gamification"],
    summary="Marcar conteudo como completo",
)
async def complete_content(
    user_id: str,
    course_id: str,
    content_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Verify content exists
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        raise HTTPException(status_code=404, detail="Conteudo nao encontrado")

    # Count total contents in the course
    total_contents = (
        db.query(func.count(Content.id))
        .join(Chapter, Chapter.id == Content.chapter_id)
        .filter(Chapter.course_id == course_id)
        .scalar()
        or 0
    )

    # Upsert course progress
    progress = (
        db.query(CourseProgress)
        .filter(CourseProgress.user_id == user_id, CourseProgress.course_id == course_id)
        .first()
    )
    if not progress:
        progress = CourseProgress(
            id=str(uuid4()),
            user_id=user_id,
            course_id=course_id,
            completed_contents=0,
            total_contents=total_contents,
        )
        db.add(progress)

    progress.completed_contents = min((progress.completed_contents or 0) + 1, total_contents)
    progress.total_contents = total_contents
    progress.progress_percent = (
        round(progress.completed_contents / total_contents * 100, 1) if total_contents > 0 else 0
    )

    # Log activity
    db.add(
        UserActivity(
            id=str(uuid4()),
            user_id=user_id,
            activity_type="content_completed",
            description=f"Conteudo {content.title} completo",
            points=10,
        )
    )

    db.commit()
    db.refresh(progress)
    return {
        "course_id": course_id,
        "content_id": content_id,
        "progress_percent": progress.progress_percent,
        "completed_contents": progress.completed_contents,
        "total_contents": progress.total_contents,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SESSION REVIEW (professor ↔ aluno)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/chat-sessions/{session_id}/review", tags=["Session Review"], summary="Criar review", status_code=201)
async def create_review(
    session_id: str,
    body: SessionReviewCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    existing = db.query(SessionReview).filter(SessionReview.session_id == session_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Review ja existe para esta sessao")

    row = SessionReview(
        id=str(uuid4()),
        session_id=session_id,
        reviewer_id=user.id,
        rating=body.rating,
        feedback=body.feedback,
        status="pending_student",
    )
    db.add(row)

    # Notify student
    db.add(
        Notification(
            id=str(uuid4()),
            user_id=session.user_id,
            title="Sessao avaliada pelo professor",
            message=body.feedback or "Sua sessao de dialogo socratico foi avaliada.",
            notification_type="review",
            link=f"/chat-sessions/{session_id}/review",
        )
    )

    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "session_id": session_id,
        "rating": row.rating,
        "feedback": row.feedback,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/chat-sessions/{session_id}/review", tags=["Session Review"], summary="Ver review")
async def get_review(
    session_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(SessionReview).filter(SessionReview.session_id == session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Review nao encontrado")

    reviewer = db.query(User).filter(User.id == row.reviewer_id).first()
    return {
        "id": row.id,
        "session_id": session_id,
        "reviewer_id": row.reviewer_id,
        "reviewer_name": reviewer.name if reviewer else None,
        "rating": row.rating,
        "feedback": row.feedback,
        "student_reply": row.student_reply,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/chat-sessions/{session_id}/review", tags=["Session Review"], summary="Atualizar review")
async def update_review(
    session_id: str,
    body: SessionReviewCreate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(SessionReview).filter(SessionReview.session_id == session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Review nao encontrado")

    if body.rating is not None:
        row.rating = body.rating
    if body.feedback is not None:
        row.feedback = body.feedback
    row.status = "pending_student"

    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "rating": row.rating,
        "feedback": row.feedback,
        "status": row.status,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/chat-sessions/{session_id}/review/reply", tags=["Session Review"], summary="Aluno responde review")
async def reply_review(
    session_id: str,
    body: SessionReviewReply,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(SessionReview).filter(SessionReview.session_id == session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Review nao encontrado")

    row.student_reply = body.reply
    row.status = "replied"

    # Notify reviewer
    db.add(
        Notification(
            id=str(uuid4()),
            user_id=row.reviewer_id,
            title="Aluno respondeu a avaliacao",
            message=f"{user.name} respondeu: {body.reply[:100]}",
            notification_type="review_reply",
            link=f"/chat-sessions/{session_id}/review",
        )
    )

    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "student_reply": row.student_reply,
        "status": row.status,
    }


@router.get(
    "/disciplines/{discipline_id}/sessions",
    tags=["Session Review"],
    summary="Sessoes de uma disciplina",
)
async def discipline_sessions(
    discipline_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Get course IDs for this discipline
    course_ids = [c.id for c in db.query(Course.id).filter(Course.discipline_id == discipline_id).all()]
    if not course_ids:
        return {"data": [], "total": 0, "page": page, "per_page": per_page, "has_more": False}

    # Get content IDs for those courses
    content_ids = [
        c.id
        for c in db.query(Content.id)
        .join(Chapter, Chapter.id == Content.chapter_id)
        .filter(Chapter.course_id.in_(course_ids))
        .all()
    ]
    if not content_ids:
        return {"data": [], "total": 0, "page": page, "per_page": per_page, "has_more": False}

    q = db.query(ChatSession).filter(ChatSession.content_id.in_(content_ids))
    if status_filter:
        q = q.filter(ChatSession.status == status_filter)

    total = q.count()
    rows = q.order_by(ChatSession.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for s in rows:
        user = db.query(User).filter(User.id == s.user_id).first()
        review = db.query(SessionReview).filter(SessionReview.session_id == s.id).first()
        result.append(
            {
                "id": s.id,
                "user_id": s.user_id,
                "user_name": user.name if user else None,
                "content_id": s.content_id,
                "status": s.status,
                "total_messages": s.total_messages,
                "performance_score": s.performance_score,
                "review_status": review.status if review else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )

    return {
        "data": result,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": total > page * per_page,
    }
