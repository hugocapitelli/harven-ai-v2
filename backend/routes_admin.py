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
from supabase import Client

from auth import get_current_user, require_role
from authz import (
    assert_owner_or_role,
    assert_teacher_owns_discipline,
    require_self_or_role,
)
from config import get_settings
from database import get_supabase
from gamification_points import points_for
from repositories.discipline_repo import DisciplineRepository

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

# URL fields in system_settings (used to filter empty strings on save)
SETTINGS_URL_FIELDS = {
    "logo_url",
    "login_logo_url",
    "login_bg_url",
    "favicon_url",
}

# Fields that must never be overwritten via the settings save endpoint
SETTINGS_READONLY_FIELDS = {"id", "created_at", "updated_at"}

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class NotificationCreate(BaseModel):
    user_id: str
    title: str = Field(..., min_length=1, max_length=255)
    message: Optional[str] = None
    notification_type: Optional[str] = Field(None, max_length=50)
    link: Optional[str] = Field(None, max_length=500)


class NotificationBroadcast(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    notification_type: Optional[str] = Field("announcement", max_length=50)
    target: Optional[str] = "all"


class ActivityCreate(BaseModel):
    activity_type: str = Field(..., max_length=50)
    description: Optional[str] = None
    points: int = 0
    metadata: Optional[dict] = None


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


def _mask_sensitive(data: dict) -> dict:
    """Mask sensitive fields: show first 4 chars + **** or 'not_configured' for null."""
    out = dict(data)
    for key in SENSITIVE_FIELDS:
        if key not in out:
            continue
        val = out[key]
        if val is None:
            out[key] = "not_configured"
        elif isinstance(val, str) and len(val) > 4:
            out[key] = val[:4] + "****"
        elif val:
            out[key] = "****"
    return out


def _sanitize_search(q: str) -> str:
    """Remove SQL wildcards and special chars, cap length."""
    sanitized = re.sub(r"[%_\\'\";]", "", q.strip())
    return sanitized[:200]


def _get_or_create_settings(client: Client) -> dict:
    """Return the single settings row or create one if missing."""
    res = (client.table("system_settings").select("*").limit(1).maybe_single().execute() or type("_R", (), {"data": None})())
    if res.data is not None:
        return res.data
    new_row = {"id": str(uuid4()), "platform_name": "Harven.AI"}
    ins = client.table("system_settings").insert(new_row).execute()
    return ins.data[0] if ins.data else new_row


def _log(client: Client, message: str, author: str = "system", log_type: str = "info", st: str = "ok"):
    """Append a row to system_logs."""
    client.table("system_logs").insert(
        {"id": str(uuid4()), "message": message, "author": author, "log_type": log_type, "status": st}
    ).execute()


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
async def get_public_settings(client: Client = Depends(get_supabase)):
    """Returns public-facing settings (no auth required)."""
    data = _get_or_create_settings(client)
    return {k: v for k, v in data.items() if k in PUBLIC_SETTINGS_FIELDS}


@router.get("/admin/settings", tags=["Admin Settings"], summary="Todas as configuracoes (admin)")
async def get_admin_settings(
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    data = _get_or_create_settings(client)
    return _mask_sensitive(data)


@router.post("/admin/settings", tags=["Admin Settings"], summary="Salvar configuracoes (admin)")
async def save_admin_settings(
    payload: dict,
    admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    row = _get_or_create_settings(client)
    row_id = row["id"]

    # Filter out empty-string URL fields so they aren't overwritten to ""
    cleaned = {k: v for k, v in payload.items() if not (k in SETTINGS_URL_FIELDS and v == "")}

    # Never accept raw sensitive fields that look like masked values
    for key in SENSITIVE_FIELDS:
        val = cleaned.get(key)
        if isinstance(val, str) and val.endswith("****"):
            cleaned.pop(key, None)

    # Remove read-only fields
    for key in SETTINGS_READONLY_FIELDS:
        cleaned.pop(key, None)

    if cleaned:
        # P0: the payload comes straight from the admin UI and may carry keys that
        # are not (yet) columns in system_settings. PostgREST rejects the WHOLE
        # batch update on a single unknown column, so one stray field silently
        # killed every other setting in the save. Try the batch first (1 round
        # trip, common case); on failure retry field-by-field so the valid fields
        # persist and only the bad ones are skipped (logged, and 400 only when
        # NOTHING could be saved).
        try:
            client.table("system_settings").update(cleaned).eq("id", row_id).execute()
        except Exception as batch_exc:
            logger.warning(
                f"settings batch update failed ({batch_exc}); retrying field-by-field"
            )
            skipped: list[str] = []
            for key, value in cleaned.items():
                try:
                    client.table("system_settings").update({key: value}).eq("id", row_id).execute()
                except Exception as field_exc:
                    skipped.append(key)
                    logger.warning(f"settings field '{key}' skipped: {field_exc}")
            if skipped:
                _log(
                    client,
                    f"Settings: campos ignorados no save ({', '.join(skipped)})",
                    author=admin["name"],
                    log_type="settings",
                )
            if skipped and len(skipped) == len(cleaned):
                raise HTTPException(
                    status_code=400,
                    detail=f"Nenhum campo pode ser salvo: {', '.join(sorted(skipped))}",
                )

    updated = _get_or_create_settings(client)
    _log(client, f"Settings atualizadas por {admin['name']}", author=admin["name"], log_type="settings")
    return _mask_sensitive(updated)


@router.post("/admin/settings/upload-logo", tags=["Admin Settings"], summary="Upload logo principal")
async def upload_logo(
    file: UploadFile = File(...),
    admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    _validate_image(file)
    url = _save_upload(file, "logos")
    row = _get_or_create_settings(client)
    client.table("system_settings").update({"logo_url": url}).eq("id", row["id"]).execute()
    _log(client, f"Logo atualizado por {admin['name']}", author=admin["name"], log_type="settings")
    return {"logo_url": url}


@router.post("/admin/settings/upload-login-logo", tags=["Admin Settings"], summary="Upload logo do login")
async def upload_login_logo(
    file: UploadFile = File(...),
    admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    _validate_image(file)
    url = _save_upload(file, "logos")
    row = _get_or_create_settings(client)
    client.table("system_settings").update({"login_logo_url": url}).eq("id", row["id"]).execute()
    _log(client, f"Login logo atualizado por {admin['name']}", author=admin["name"], log_type="settings")
    return {"login_logo_url": url}


@router.post("/admin/settings/upload-login-bg", tags=["Admin Settings"], summary="Upload background do login")
async def upload_login_bg(
    file: UploadFile = File(...),
    admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    _validate_image(file)
    url = _save_upload(file, "backgrounds")
    row = _get_or_create_settings(client)
    client.table("system_settings").update({"login_bg_url": url}).eq("id", row["id"]).execute()
    _log(client, f"Login background atualizado por {admin['name']}", author=admin["name"], log_type="settings")
    return {"login_bg_url": url}


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN MONITORING
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/admin/stats", tags=["Admin Monitoring"], summary="Estatisticas gerais")
async def admin_stats(
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    users_res = client.table("users").select("id", count="exact").execute()
    users_total = users_res.count or 0

    # Users by role
    all_users = client.table("users").select("role").execute()
    users_by_role: dict[str, int] = {}
    for u in (all_users.data or []):
        role = u.get("role", "unknown")
        users_by_role[role] = users_by_role.get(role, 0) + 1

    courses_res = client.table("courses").select("id", count="exact").execute()
    courses_total = courses_res.count or 0

    disciplines_res = client.table("disciplines").select("id", count="exact").execute()
    disciplines_total = disciplines_res.count or 0

    sessions_res = client.table("chat_sessions").select("id", count="exact").execute()
    sessions_total = sessions_res.count or 0

    messages_res = client.table("chat_messages").select("id", count="exact").execute()
    messages_total = messages_res.count or 0

    notifications_res = client.table("notifications").select("id", count="exact").execute()
    notifications_total = notifications_res.count or 0

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
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    # Fetch sessions that have a performance_score
    scored = client.table("chat_sessions").select("performance_score, total_messages").not_.is_("performance_score", "null").execute()
    rows = scored.data or []

    if rows:
        scores = [r["performance_score"] for r in rows if r.get("performance_score") is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
    else:
        avg_score = 0

    all_sessions = client.table("chat_sessions").select("total_messages").execute()
    all_rows = all_sessions.data or []
    if all_rows:
        msgs = [r.get("total_messages") or 0 for r in all_rows]
        avg_messages = sum(msgs) / len(msgs) if msgs else 0
    else:
        avg_messages = 0

    active_res = client.table("chat_sessions").select("id", count="exact").eq("status", "active").execute()
    active_sessions = active_res.count or 0

    return {
        "avg_performance_score": round(float(avg_score), 2),
        "avg_messages_per_session": round(float(avg_messages), 1),
        "active_sessions": active_sessions,
    }


@router.get("/admin/storage", tags=["Admin Monitoring"], summary="Uso de armazenamento")
async def admin_storage(
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
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
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    q = client.table("system_logs").select("*", count="exact")
    if log_type:
        q = q.eq("log_type", log_type)
    total_res = q.order("created_at", desc=True).range((page - 1) * per_page, page * per_page - 1).execute()
    total = total_res.count or 0
    rows = total_res.data or []

    return {
        "data": [
            {
                "id": r.get("id"),
                "message": r.get("message"),
                "author": r.get("author"),
                "status": r.get("status"),
                "log_type": r.get("log_type"),
                "details": r.get("details"),
                "created_at": r.get("created_at"),
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
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    query = client.table("system_logs").select("*", count="exact")
    if q:
        safe = _sanitize_search(q)
        query = query.or_(f"message.ilike.%{safe}%,author.ilike.%{safe}%")
    if log_type:
        query = query.eq("log_type", log_type)
    if status_filter:
        query = query.eq("status", status_filter)

    total_res = query.order("created_at", desc=True).range((page - 1) * per_page, page * per_page - 1).execute()
    total = total_res.count or 0
    rows = total_res.data or []

    return {
        "data": [
            {
                "id": r.get("id"),
                "message": r.get("message"),
                "author": r.get("author"),
                "status": r.get("status"),
                "log_type": r.get("log_type"),
                "details": r.get("details"),
                "created_at": r.get("created_at"),
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
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    from fastapi.responses import StreamingResponse

    res = client.table("system_logs").select("*").order("created_at", desc=True).limit(5000).execute()
    rows = res.data or []

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "message", "author", "status", "log_type", "created_at"])
        for r in rows:
            writer.writerow([r.get("id"), r.get("message"), r.get("author"), r.get("status"), r.get("log_type"), r.get("created_at")])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=logs.csv"},
        )

    data = [
        {
            "id": r.get("id"),
            "message": r.get("message"),
            "author": r.get("author"),
            "status": r.get("status"),
            "log_type": r.get("log_type"),
            "created_at": r.get("created_at"),
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
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    res = client.table("system_backups").select("*").order("created_at", desc=True).execute()
    rows = res.data or []
    return {
        "data": [
            {
                "id": r.get("id"),
                "filename": r.get("filename"),
                "size": r.get("size"),
                "records_count": r.get("records_count"),
                "status": r.get("status"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]
    }


@router.post("/admin/backups", tags=["Admin Backups"], summary="Criar backup", status_code=201)
async def create_backup(
    admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    settings = get_settings()
    backup_dir = os.path.join(settings.UPLOAD_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{ts}.json"
    filepath = os.path.join(backup_dir, filename)

    # Collect counts per table
    users_cnt = (client.table("users").select("id", count="exact").execute()).count or 0
    courses_cnt = (client.table("courses").select("id", count="exact").execute()).count or 0
    disciplines_cnt = (client.table("disciplines").select("id", count="exact").execute()).count or 0
    sessions_cnt = (client.table("chat_sessions").select("id", count="exact").execute()).count or 0

    counts = {
        "users": users_cnt,
        "courses": courses_cnt,
        "disciplines": disciplines_cnt,
        "chat_sessions": sessions_cnt,
    }
    total_records = sum(counts.values())

    # Write metadata file (actual DB dump would be done by a dedicated job)
    meta = {"created_at": ts, "tables": counts, "total_records": total_records}
    with open(filepath, "w") as f:
        json.dump(meta, f, indent=2)

    fsize = os.path.getsize(filepath)
    new_id = str(uuid4())
    client.table("system_backups").insert(
        {
            "id": new_id,
            "filename": filename,
            "size": fsize,
            "records_count": total_records,
            "status": "completed",
            "storage_path": filepath,
        }
    ).execute()

    _log(client, f"Backup criado: {filename}", author=admin["name"], log_type="backup")

    return {
        "id": new_id,
        "filename": filename,
        "size": fsize,
        "records_count": total_records,
        "status": "completed",
    }


@router.get("/admin/backups/{backup_id}/download", tags=["Admin Backups"], summary="Download backup")
async def download_backup(
    backup_id: str,
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    from fastapi.responses import FileResponse

    res = (client.table("system_backups").select("*").eq("id", backup_id).maybe_single().execute() or type("_R", (), {"data": None})())
    row = res.data
    if not row:
        raise HTTPException(status_code=404, detail="Backup nao encontrado")
    storage_path = row.get("storage_path")
    if not storage_path or not os.path.isfile(storage_path):
        raise HTTPException(status_code=404, detail="Arquivo de backup nao encontrado no disco")
    return FileResponse(storage_path, filename=row.get("filename"), media_type="application/json")


@router.delete("/admin/backups/{backup_id}", tags=["Admin Backups"], summary="Excluir backup")
async def delete_backup(
    backup_id: str,
    admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    res = (client.table("system_backups").select("*").eq("id", backup_id).maybe_single().execute() or type("_R", (), {"data": None})())
    row = res.data
    if not row:
        raise HTTPException(status_code=404, detail="Backup nao encontrado")
    storage_path = row.get("storage_path")
    if storage_path and os.path.isfile(storage_path):
        os.remove(storage_path)
    client.table("system_backups").delete().eq("id", backup_id).execute()
    _log(client, f"Backup excluido: {row.get('filename')}", author=admin["name"], log_type="backup")
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN SECURITY
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/admin/force-logout", tags=["Admin Security"], summary="Invalidar todos os tokens")
async def force_logout(
    admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    """
    Rotate the JWT secret so every existing token becomes invalid.

    SEC-ROT-3: the secret is rotated **in the database** (system_settings) and the
    provider cache is invalidated immediately, so verification picks up the new
    secret on the next request — no restart, no filesystem write. The previous
    behaviour (rewriting .env) was inert in production because docker-compose env
    vars outrank the .env file in pydantic-settings precedence (bug #22).
    """
    from datetime import datetime, timezone

    from jwt_secret_provider import invalidate_jwt_secret_cache

    new_secret = secrets.token_urlsafe(48)

    # Rotate the active signing secret in the DB (durable source of truth).
    row = _get_or_create_settings(client)
    client.table("system_settings").update(
        {
            "jwt_secret": new_secret,
            "jwt_secret_rotated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", row["id"]).execute()

    # Drop the provider cache so the new secret takes effect immediately
    # (do not wait for the TTL). All pre-rotation tokens now fail verification.
    invalidate_jwt_secret_cache()

    _log(client, f"Force logout executado por {admin['name']}", author=admin["name"], log_type="security")
    return {"message": "Todos os tokens foram invalidados. Usuarios deverao fazer login novamente."}


@router.post("/admin/clear-cache", tags=["Admin Security"], summary="Limpar cache interno")
async def clear_cache(
    admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    from config import get_settings as _gs
    _gs.cache_clear()
    _log(client, f"Cache limpo por {admin['name']}", author=admin["name"], log_type="security")
    return {"message": "Cache interno limpo com sucesso."}


# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/users/{user_id}/notifications/count", tags=["Notifications"], summary="Contagem de nao lidas (alias)")
@router.get("/notifications/{user_id}/count", tags=["Notifications"], summary="Contagem de nao lidas")
async def notification_count(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # IDOR gate (SEC-ADMIN-3): only the owner of {user_id}, or an ADMIN, may read.
    require_self_or_role(user_id, current_user, "ADMIN")
    res = (
        client.table("notifications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("is_read", False)
        .execute()
    )
    return {"unread": res.count or 0}


@router.get("/users/{user_id}/notifications", tags=["Notifications"], summary="Listar notificacoes (alias)")
@router.get("/notifications/{user_id}", tags=["Notifications"], summary="Listar notificacoes")
async def list_notifications(
    user_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # IDOR gate (SEC-ADMIN-3): only the owner of {user_id}, or an ADMIN, may read.
    require_self_or_role(user_id, current_user, "ADMIN")
    res = (
        client.table("notifications")
        .select("*", count="exact")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range((page - 1) * per_page, page * per_page - 1)
        .execute()
    )
    total = res.count or 0
    rows = res.data or []

    return {
        "data": [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "message": r.get("message"),
                "type": r.get("notification_type"),
                "link": r.get("link"),
                "read": r.get("is_read"),
                "created_at": r.get("created_at"),
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
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    # Creation is an ADMIN/system operation (SEC-ADMIN-3). Only here is
    # ``body.user_id`` a legitimate target — never in a student-facing route.
    new_id = str(uuid4())
    res = client.table("notifications").insert(
        {
            "id": new_id,
            "user_id": body.user_id,
            "title": body.title,
            "message": body.message,
            "notification_type": body.notification_type,
            "link": body.link,
        }
    ).execute()
    row = res.data[0] if res.data else {}
    return {
        "id": row.get("id", new_id),
        "title": row.get("title", body.title),
        "message": row.get("message", body.message),
        "type": row.get("notification_type", body.notification_type),
        "created_at": row.get("created_at"),
    }


@router.post("/notifications/broadcast", tags=["Notifications"], summary="Enviar notificacao em massa")
async def broadcast_notification(
    body: NotificationBroadcast,
    _admin: dict = Depends(require_role("ADMIN")),
    client: Client = Depends(get_supabase),
):
    # Fan-out is an ADMIN-only operation (mirrors create_notification's ADMIN
    # gate) — resolves recipients server-side and inserts one notification row
    # per recipient in a single batch call.
    target = (body.target or "all").lower()
    if target == "all":
        users_res = client.table("users").select("id").execute()
    else:
        users_res = client.table("users").select("id").eq("role", target.upper()).execute()
    recipients = users_res.data or []

    if not recipients:
        return {"sent": 0}

    rows = [
        {
            "id": str(uuid4()),
            "user_id": r["id"],
            "title": body.title,
            "message": body.message,
            "notification_type": body.notification_type,
            "link": None,
        }
        for r in recipients
    ]
    client.table("notifications").insert(rows).execute()
    return {"sent": len(rows)}


@router.put("/notifications/{notification_id}/read", tags=["Notifications"], summary="Marcar como lida")
async def mark_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # Existence first (404), then ownership of the loaded row (403) — SEC-ADMIN-3.
    res = (client.table("notifications").select("id, user_id").eq("id", notification_id).maybe_single().execute() or type("_R", (), {"data": None})())
    if not res.data:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada")
    assert_owner_or_role(res.data.get("user_id"), current_user, "ADMIN")
    client.table("notifications").update({"is_read": True}).eq("id", notification_id).execute()
    return {"id": notification_id, "read": True}


@router.put("/notifications/{user_id}/read-all", tags=["Notifications"], summary="Marcar todas como lidas")
async def mark_all_read(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # IDOR gate (SEC-ADMIN-3): only the owner of {user_id}, or an ADMIN, may
    # suppress this feed — checked before any update touches another user's rows.
    require_self_or_role(user_id, current_user, "ADMIN")
    # Supabase doesn't return an update count directly; update all matching rows
    client.table("notifications").update({"is_read": True}).eq("user_id", user_id).eq("is_read", False).execute()
    # Count remaining unread to confirm (should be 0)
    remaining = client.table("notifications").select("id", count="exact").eq("user_id", user_id).eq("is_read", False).execute()
    marked = (remaining.count or 0)
    return {"marked_read": "all", "remaining_unread": marked}


@router.delete("/notifications/{notification_id}", tags=["Notifications"], summary="Excluir notificacao")
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # Existence first (404), then ownership of the loaded row (403) — SEC-ADMIN-3.
    res = (client.table("notifications").select("id, user_id").eq("id", notification_id).maybe_single().execute() or type("_R", (), {"data": None})())
    if not res.data:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada")
    assert_owner_or_role(res.data.get("user_id"), current_user, "ADMIN")
    client.table("notifications").delete().eq("id", notification_id).execute()
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/search", tags=["Search"], summary="Busca global")
async def global_search(
    q: str = Query(..., min_length=2, max_length=200),
    # P1: this search returns users (name/email/RA), draft courses and every
    # discipline — gated only by get_current_user it exposed the WHOLE base to
    # any student. Cross-user search is a staff capability.
    _user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    safe = _sanitize_search(q)
    if len(safe) < 2:
        return {"users": [], "courses": [], "disciplines": []}

    users_res = (
        client.table("users")
        .select("id, name, email, role, ra")
        .or_(f"name.ilike.%{safe}%,email.ilike.%{safe}%,ra.ilike.%{safe}%")
        .limit(10)
        .execute()
    )
    courses_res = (
        client.table("courses")
        .select("id, title, status, discipline_id")
        .or_(f"title.ilike.%{safe}%,description.ilike.%{safe}%")
        .limit(10)
        .execute()
    )
    disciplines_res = (
        client.table("disciplines")
        .select("id, name, code")
        .or_(f"name.ilike.%{safe}%,code.ilike.%{safe}%")
        .limit(10)
        .execute()
    )

    return {
        "users": [
            {"id": u.get("id"), "name": u.get("name"), "email": u.get("email"), "role": u.get("role"), "ra": u.get("ra")}
            for u in (users_res.data or [])
        ],
        "courses": [
            {"id": c.get("id"), "title": c.get("title"), "status": c.get("status"), "discipline_id": c.get("discipline_id")}
            for c in (courses_res.data or [])
        ],
        "disciplines": [
            {"id": d.get("id"), "name": d.get("name"), "code": d.get("code")}
            for d in (disciplines_res.data or [])
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/dashboard/stats", tags=["Dashboard"], summary="Estatisticas agregadas")
async def dashboard_stats(
    # P1: institutional aggregates (total users, role breakdown, average
    # performance score) were readable by any STUDENT. Staff-only.
    _user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    total_users = (client.table("users").select("id", count="exact").execute()).count or 0
    total_courses = (client.table("courses").select("id", count="exact").execute()).count or 0
    total_disciplines = (client.table("disciplines").select("id", count="exact").execute()).count or 0
    total_sessions = (client.table("chat_sessions").select("id", count="exact").execute()).count or 0

    # Users by role breakdown
    all_users = client.table("users").select("role").execute()
    by_role: dict[str, int] = {}
    for u in (all_users.data or []):
        role = u.get("role", "unknown")
        by_role[role] = by_role.get(role, 0) + 1

    scored = client.table("chat_sessions").select("performance_score").not_.is_("performance_score", "null").execute()
    scores = [r["performance_score"] for r in (scored.data or []) if r.get("performance_score") is not None]
    avg_score = sum(scores) / len(scores) if scores else 0

    return {
        "total_users": total_users,
        "users_by_role": by_role,
        "total_courses": total_courses,
        "total_disciplines": total_disciplines,
        "total_sessions": total_sessions,
        "avg_performance_score": round(float(avg_score), 2),
    }


@router.get("/classes/{class_id}/stats", tags=["Dashboard"], summary="Estatisticas de turma")
async def class_stats(
    class_id: str,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER")),
    client: Client = Depends(get_supabase),
):
    """class_id maps to a Discipline id."""
    # Role gate (require_role) rejects STUDENT with 403 before any read.
    # Existence (404) is preserved for authorized callers, then the teacher
    # discipline-scoping gate runs (ADMIN bypasses) — SEC-SCOPE-1.
    disc_res = (client.table("disciplines").select("id, name").eq("id", class_id).maybe_single().execute() or type("_R", (), {"data": None})())
    disc = disc_res.data
    if not disc:
        raise HTTPException(status_code=404, detail="Turma nao encontrada")

    assert_teacher_owns_discipline(class_id, current_user, DisciplineRepository(client))

    student_res = client.table("discipline_students").select("id", count="exact").eq("discipline_id", class_id).execute()
    student_count = student_res.count or 0

    course_res = client.table("courses").select("id", count="exact").eq("discipline_id", class_id).execute()
    course_count = course_res.count or 0

    # Sessions from students in this discipline
    students_res = client.table("discipline_students").select("student_id").eq("discipline_id", class_id).execute()
    student_ids = [s["student_id"] for s in (students_res.data or [])]

    session_count = 0
    if student_ids:
        session_res = client.table("chat_sessions").select("id", count="exact").in_("user_id", student_ids).execute()
        session_count = session_res.count or 0

    return {
        "discipline_id": class_id,
        "discipline_name": disc.get("name"),
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
    current_user: dict = Depends(require_role("ADMIN", "TEACHER")),
    client: Client = Depends(get_supabase),
):
    # Role gate (403 for STUDENT) -> existence (404) -> teacher scoping (403) -> read.
    disc_res = (client.table("disciplines").select("id, name").eq("id", discipline_id).maybe_single().execute() or type("_R", (), {"data": None})())
    disc = disc_res.data
    if not disc:
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")

    assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))

    # Get student IDs for this discipline
    ds_res = client.table("discipline_students").select("student_id").eq("discipline_id", discipline_id).execute()
    student_ids = [s["student_id"] for s in (ds_res.data or [])]

    if not student_ids:
        return {"discipline_id": discipline_id, "discipline_name": disc.get("name"), "students": []}

    # Fetch user info for these students
    users_res = client.table("users").select("id, name, ra").in_("id", student_ids).execute()
    users_map = {u["id"]: u for u in (users_res.data or [])}

    # Fetch all sessions for these students
    sessions_res = client.table("chat_sessions").select("user_id, performance_score").in_("user_id", student_ids).execute()

    # Aggregate per student
    student_sessions: dict[str, list] = {sid: [] for sid in student_ids}
    for s in (sessions_res.data or []):
        uid = s.get("user_id")
        if uid in student_sessions:
            student_sessions[uid].append(s)

    students = []
    for sid in student_ids:
        u = users_map.get(sid, {})
        sess = student_sessions.get(sid, [])
        scores = [s["performance_score"] for s in sess if s.get("performance_score") is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        students.append(
            {
                "id": sid,
                "name": u.get("name"),
                "ra": u.get("ra"),
                "sessions": len(sess),
                "avg_score": round(float(avg_score), 2),
            }
        )

    return {
        "discipline_id": discipline_id,
        "discipline_name": disc.get("name"),
        "students": students,
    }


# ═══════════════════════════════════════════════════════════════════════════
# GAMIFICATION
# ═══════════════════════════════════════════════════════════════════════════


def _effective_write_target(path_user_id: str, current_user: dict) -> str:
    """Resolve the user_id a gamification write should land on (SEC-ADMIN-4).

    Self-service is the rule: a non-privileged actor always writes to their own
    authenticated id (``current_user["id"]``) — the ``path_user_id`` is never
    trusted to redirect a self-service write. ADMIN/TEACHER may legitimately
    operate on behalf of another user, so for them the (already authorized)
    ``path_user_id`` is honoured. Callers MUST run ``assert_owner_or_role`` first.
    """
    role = str((current_user or {}).get("role") or "").strip().upper()
    actor_id = str((current_user or {}).get("id") or "")
    if role in {"ADMIN", "TEACHER"} and str(path_user_id) != actor_id:
        return str(path_user_id)
    return actor_id


@router.get("/users/{user_id}/stats", tags=["Gamification"], summary="Stats do usuario")
async def user_stats(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-READ-1: read IDOR fix — owner (path == token) reads their own stats;
    # only ADMIN/TEACHER may read another user's. Everyone else -> 403, no read.
    require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")
    try:
        res = (client.table("user_stats").select("*").eq("user_id", user_id).maybe_single().execute() or type("_R", (), {"data": None})())
        row = res.data if res else None
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
            "courses_completed": row.get("courses_completed", 0),
            "hours_studied": row.get("hours_studied", 0.0),
            "average_score": row.get("average_score", 0.0),
            "streak_days": row.get("streak_days", 0),
            "total_points": row.get("total_points", 0),
        }
    except Exception as e:
        error_msg = str(e).lower()
        if "relation" in error_msg or "does not exist" in error_msg or "undefined_table" in error_msg:
            raise HTTPException(
                status_code=503,
                detail="Tabelas de gamificacao nao encontradas. Execute as migrations do banco de dados.",
            )
        logger.error(f"user_stats error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.get("/users/{user_id}/activities", tags=["Gamification"], summary="Atividades do usuario")
async def user_activities(
    user_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-READ-1: read IDOR fix — owner reads their own activities; only
    # ADMIN/TEACHER may read another user's. Everyone else -> 403, no read.
    require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")
    res = (
        client.table("user_activities")
        .select("*", count="exact")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range((page - 1) * per_page, page * per_page - 1)
        .execute()
    )
    total = res.count or 0
    rows = res.data or []

    return {
        "data": [
            {
                "id": r.get("id"),
                "activity_type": r.get("activity_type"),
                "description": r.get("description"),
                "points": r.get("points"),
                "metadata": r.get("metadata"),
                "created_at": r.get("created_at"),
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
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-ADMIN-4: self-service write — owner (path == token) passes; only
    # ADMIN/TEACHER may write for another user_id; everyone else -> 403, no write.
    assert_owner_or_role(user_id, current_user, "ADMIN", "TEACHER")
    target_user_id = _effective_write_target(user_id, current_user)
    # Points are server-decided (whitelist) — body.points is ignored.
    award = points_for(body.activity_type)
    try:
        new_id = str(uuid4())
        res = client.table("user_activities").insert(
            {
                "id": new_id,
                "user_id": target_user_id,
                "activity_type": body.activity_type,
                "description": body.description,
                "points": award,
                "metadata": body.metadata,
            }
        ).execute()
        row = res.data[0] if res.data else {}

        # Update user stats (upsert)
        stats_res = (client.table("user_stats").select("*").eq("user_id", target_user_id).maybe_single().execute() or type("_R", (), {"data": None})())
        if stats_res.data:
            current_points = stats_res.data.get("total_points", 0) or 0
            client.table("user_stats").update(
                {"total_points": current_points + award}
            ).eq("user_id", target_user_id).execute()
        else:
            client.table("user_stats").insert(
                {"id": str(uuid4()), "user_id": target_user_id, "total_points": award}
            ).execute()

        return {
            "id": row.get("id", new_id),
            "activity_type": row.get("activity_type", body.activity_type),
            "points": row.get("points", award),
            "created_at": row.get("created_at"),
        }
    except Exception as e:
        error_msg = str(e).lower()
        if "relation" in error_msg or "does not exist" in error_msg or "undefined_table" in error_msg:
            raise HTTPException(
                status_code=503,
                detail="Tabelas de gamificacao nao encontradas. Execute as migrations do banco de dados.",
            )
        logger.error(f"create_activity error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.get("/users/{user_id}/achievements", tags=["Gamification"], summary="Conquistas do usuario")
async def user_achievements(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-READ-1: read IDOR fix — owner reads their own achievements; only
    # ADMIN/TEACHER may read another user's. Everyone else -> 403, no read.
    require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")
    res = (
        client.table("user_achievements")
        .select("*")
        .eq("user_id", user_id)
        .order("unlocked_at", desc=True)
        .execute()
    )
    rows = res.data or []
    return {
        "data": [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "description": r.get("description"),
                "icon": r.get("icon"),
                "category": r.get("category"),
                "rarity": r.get("rarity"),
                "points": r.get("points"),
                "unlocked_at": r.get("unlocked_at"),
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
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-ADMIN-4: authorize BEFORE dedup/insert. Owner or ADMIN/TEACHER only.
    assert_owner_or_role(user_id, current_user, "ADMIN", "TEACHER")
    target_user_id = _effective_write_target(user_id, current_user)

    # Prevent duplicates.
    # GRD-5: supabase-py 2.28.x returns ``None`` (not a response with ``data=None``)
    # from ``.maybe_single().execute()`` on ZERO rows — the first unlock of an
    # achievement has no existing row, so a bare ``existing_res.data`` raised
    # AttributeError -> 500. The ``or type(...)`` idiom (used elsewhere in this file)
    # normalizes the no-row case to a ``data=None`` sentinel. Precedent: commit 5847a60.
    existing_res = (
        client.table("user_achievements")
        .select("*")
        .eq("user_id", target_user_id)
        .eq("id", achievement_id)
        .maybe_single()
        .execute()
        or type("_R", (), {"data": None})()
    )
    if existing_res.data:
        return {
            "id": existing_res.data.get("id"),
            "name": existing_res.data.get("name"),
            "already_unlocked": True,
        }

    now = datetime.now(timezone.utc).isoformat()
    res = client.table("user_achievements").insert(
        {
            "id": achievement_id,
            "user_id": target_user_id,
            "name": achievement_id,
            "unlocked_at": now,
        }
    ).execute()
    row = res.data[0] if res.data else {}
    return {
        "id": row.get("id", achievement_id),
        "name": row.get("name", achievement_id),
        "unlocked_at": row.get("unlocked_at", now),
    }


@router.get("/users/{user_id}/certificates", tags=["Gamification"], summary="Certificados do usuario")
async def user_certificates(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-READ-1: read IDOR fix — owner reads their own certificates; only
    # ADMIN/TEACHER may read another user's. Everyone else -> 403, no read.
    require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")
    res = (
        client.table("certificates")
        .select("*")
        .eq("user_id", user_id)
        .order("issued_at", desc=True)
        .execute()
    )
    rows = res.data or []
    return {
        "data": [
            {
                "id": r.get("id"),
                "course_id": r.get("course_id"),
                "certificate_number": r.get("certificate_number"),
                "issued_at": r.get("issued_at"),
            }
            for r in rows
        ]
    }


@router.post("/users/{user_id}/certificates", tags=["Gamification"], summary="Emitir certificado", status_code=201)
async def issue_certificate(
    user_id: str,
    body: CertificateCreate,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-ADMIN-4: authorize first (owner or ADMIN/TEACHER), then resolve target.
    assert_owner_or_role(user_id, current_user, "ADMIN", "TEACHER")
    target_user_id = _effective_write_target(user_id, current_user)

    # Academic integrity: a non-privileged actor may only self-issue a certificate
    # once the course is fully completed (progress_percent >= 100, server-checked).
    # ADMIN/TEACHER may issue administratively, regardless of progress.
    role = str((current_user or {}).get("role") or "").strip().upper()
    if role not in {"ADMIN", "TEACHER"}:
        prog_res = (
            client.table("course_progress")
            .select("progress_percent")
            .eq("user_id", target_user_id)
            .eq("course_id", body.course_id)
            .maybe_single()
            .execute()
            or type("_R", (), {"data": None})()
        )
        prog = prog_res.data or {}
        if float(prog.get("progress_percent") or 0) < 100:
            raise HTTPException(
                status_code=403,
                detail="Certificado indisponivel: curso nao concluido (100% necessario).",
            )

    # Prevent duplicate.
    # GRD-5: zero-row ``.maybe_single().execute()`` returns ``None`` on supabase-py
    # 2.28.x — the first certificate for a course has no existing row, so a bare
    # ``existing_res.data`` raised AttributeError -> 500. Normalize with the
    # ``or type(...)`` sentinel (precedent 5847a60).
    existing_res = (
        client.table("certificates")
        .select("*")
        .eq("user_id", target_user_id)
        .eq("course_id", body.course_id)
        .maybe_single()
        .execute()
        or type("_R", (), {"data": None})()
    )
    if existing_res.data:
        return {
            "id": existing_res.data.get("id"),
            "certificate_number": existing_res.data.get("certificate_number"),
            "already_issued": True,
        }

    cert_number = f"HARVEN-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    new_id = str(uuid4())
    res = client.table("certificates").insert(
        {
            "id": new_id,
            "user_id": target_user_id,
            "course_id": body.course_id,
            "certificate_number": cert_number,
            "issued_at": now,
        }
    ).execute()
    row = res.data[0] if res.data else {}
    return {
        "id": row.get("id", new_id),
        "certificate_number": row.get("certificate_number", cert_number),
        "issued_at": row.get("issued_at", now),
    }


@router.get(
    "/users/{user_id}/courses/{course_id}/progress",
    tags=["Gamification"],
    summary="Progresso do usuario no curso",
)
async def user_course_progress(
    user_id: str,
    course_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-READ-1: read IDOR fix — owner reads their own course progress; only
    # ADMIN/TEACHER may read another user's. Everyone else -> 403, no read.
    require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")
    try:
        res = (
            client.table("course_progress")
            .select("*")
            .eq("user_id", user_id)
            .eq("course_id", course_id)
            .maybe_single()
            .execute()
        )
        row = res.data
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
            "progress_percent": row.get("progress_percent", 0.0),
            "completed_contents": row.get("completed_contents", 0),
            "total_contents": row.get("total_contents", 0),
            "updated_at": row.get("updated_at"),
        }
    except Exception as e:
        error_msg = str(e).lower()
        if "relation" in error_msg or "does not exist" in error_msg or "undefined_table" in error_msg:
            raise HTTPException(
                status_code=503,
                detail="Tabelas de gamificacao nao encontradas. Execute as migrations do banco de dados.",
            )
        logger.error(f"user_course_progress error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post(
    "/users/{user_id}/courses/{course_id}/complete-content/{content_id}",
    tags=["Gamification"],
    summary="Marcar conteudo como completo",
)
async def complete_content(
    user_id: str,
    course_id: str,
    content_id: str,
    current_user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-ADMIN-4: authorize (owner or ADMIN/TEACHER), then resolve write target.
    assert_owner_or_role(user_id, current_user, "ADMIN", "TEACHER")
    target_user_id = _effective_write_target(user_id, current_user)
    try:
        # Verify content exists
        content_res = (client.table("contents").select("id, title").eq("id", content_id).maybe_single().execute() or type("_R", (), {"data": None})())
        content = content_res.data
        if not content:
            raise HTTPException(status_code=404, detail="Conteudo nao encontrado")

        # Count total contents in the course: chapters belonging to course_id, then contents in those chapters
        chapters_res = client.table("chapters").select("id").eq("course_id", course_id).execute()
        chapter_ids = [ch["id"] for ch in (chapters_res.data or [])]

        total_contents = 0
        if chapter_ids:
            contents_res = client.table("contents").select("id", count="exact").in_("chapter_id", chapter_ids).execute()
            total_contents = contents_res.count or 0

        # P0: record WHICH content was completed, idempotently per
        # (user_id, content_id). Before this, only a bare counter was bumped —
        # repeat-clicking the same content inflated progress and nobody could
        # audit what a student actually finished. Degrades gracefully when the
        # content_completions table has not been migrated yet (counter-only,
        # legacy behavior) instead of 503ing the whole endpoint.
        already_completed = False
        completions_available = True
        try:
            comp_res = (
                client.table("content_completions")
                .select("id")
                .eq("user_id", target_user_id)
                .eq("content_id", content_id)
                .limit(1)
                .execute()
            )
            already_completed = bool(getattr(comp_res, "data", None))
        except Exception as comp_err:
            comp_msg = str(comp_err).lower()
            if "relation" in comp_msg or "does not exist" in comp_msg or "undefined_table" in comp_msg:
                completions_available = False
                logger.warning(
                    "content_completions table missing — falling back to counter-only progress"
                )
            else:
                raise

        if completions_available and not already_completed:
            try:
                client.table("content_completions").insert(
                    {
                        "id": str(uuid4()),
                        "user_id": target_user_id,
                        "content_id": content_id,
                        "course_id": course_id,
                    }
                ).execute()
            except Exception as ins_err:
                ins_msg = str(ins_err).lower()
                # Concurrent double-click: the UNIQUE(user_id, content_id) index
                # already holds the row — treat as completed, don't double-count.
                if "unique" in ins_msg or "duplicate" in ins_msg or "23505" in ins_msg:
                    already_completed = True
                else:
                    raise

        # Upsert course progress
        progress_res = (
            client.table("course_progress")
            .select("*")
            .eq("user_id", target_user_id)
            .eq("course_id", course_id)
            .maybe_single()
            .execute()
        )
        progress = progress_res.data if progress_res else None

        if already_completed:
            # Idempotent replay: return the CURRENT progress untouched — no counter
            # bump, no duplicate activity/points.
            completed_contents = (progress or {}).get("completed_contents") or 0
            progress_percent = round(completed_contents / total_contents * 100, 1) if total_contents > 0 else 0
            return {
                "course_id": course_id,
                "content_id": content_id,
                "progress_percent": progress_percent,
                "completed_contents": completed_contents,
                "total_contents": total_contents,
                "already_completed": True,
            }

        if not progress:
            new_completed = 1
            progress_percent = round(new_completed / total_contents * 100, 1) if total_contents > 0 else 0
            new_id = str(uuid4())
            client.table("course_progress").insert(
                {
                    "id": new_id,
                    "user_id": target_user_id,
                    "course_id": course_id,
                    "completed_contents": new_completed,
                    "total_contents": total_contents,
                    "progress_percent": progress_percent,
                }
            ).execute()
            completed_contents = new_completed
        else:
            completed_contents = min((progress.get("completed_contents") or 0) + 1, total_contents)
            progress_percent = round(completed_contents / total_contents * 100, 1) if total_contents > 0 else 0
            client.table("course_progress").update(
                {
                    "completed_contents": completed_contents,
                    "total_contents": total_contents,
                    "progress_percent": progress_percent,
                }
            ).eq("id", progress["id"]).execute()

        # Log activity — points from the central server-side whitelist (no hardcode).
        client.table("user_activities").insert(
            {
                "id": str(uuid4()),
                "user_id": target_user_id,
                "activity_type": "content_completed",
                "description": f"Conteudo {content.get('title', '')} completo",
                "points": points_for("content_completed"),
            }
        ).execute()

        return {
            "course_id": course_id,
            "content_id": content_id,
            "progress_percent": progress_percent,
            "completed_contents": completed_contents,
            "total_contents": total_contents,
        }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e).lower()
        if "relation" in error_msg or "does not exist" in error_msg or "undefined_table" in error_msg:
            raise HTTPException(
                status_code=503,
                detail="Tabelas de gamificacao nao encontradas. Execute as migrations do banco de dados.",
            )
        logger.error(f"complete_content error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post(
    "/courses/{course_id}/complete",
    tags=["Gamification"],
    summary="Marcar curso como completo",
)
async def complete_course(
    course_id: str,
    user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    user_id = user.get("id")
    # Verify course exists
    course_res = (
        client.table("courses").select("id, title").eq("id", course_id).maybe_single().execute()
        or type("_R", (), {"data": None})()
    )
    course = course_res.data
    if not course:
        raise HTTPException(status_code=404, detail="Curso nao encontrado")

    # Count total contents (chapters -> contents)
    chapters_res = client.table("chapters").select("id").eq("course_id", course_id).execute()
    chapter_ids = [ch["id"] for ch in (chapters_res.data or [])]
    total_contents = 0
    if chapter_ids:
        contents_res = (
            client.table("contents").select("id", count="exact").in_("chapter_id", chapter_ids).execute()
        )
        total_contents = contents_res.count or 0

    # Upsert course_progress to 100%
    progress_res = (
        client.table("course_progress")
        .select("*")
        .eq("user_id", user_id)
        .eq("course_id", course_id)
        .maybe_single()
        .execute()
    )
    progress = progress_res.data
    already_completed = bool(progress and (progress.get("progress_percent") or 0) >= 100)

    if progress:
        client.table("course_progress").update(
            {
                "progress_percent": 100.0,
                "completed_contents": total_contents,
                "total_contents": total_contents,
            }
        ).eq("id", progress["id"]).execute()
    else:
        client.table("course_progress").insert(
            {
                "id": str(uuid4()),
                "user_id": user_id,
                "course_id": course_id,
                "progress_percent": 100.0,
                "completed_contents": total_contents,
                "total_contents": total_contents,
            }
        ).execute()

    # Increment user_stats.courses_completed (only on first completion)
    if not already_completed:
        stats_res = (
            client.table("user_stats").select("*").eq("user_id", user_id).maybe_single().execute()
            or type("_R", (), {"data": None})()
        )
        if stats_res.data:
            current = stats_res.data.get("courses_completed", 0) or 0
            client.table("user_stats").update(
                {"courses_completed": current + 1}
            ).eq("user_id", user_id).execute()
        else:
            client.table("user_stats").insert(
                {
                    "id": str(uuid4()),
                    "user_id": user_id,
                    "courses_completed": 1,
                }
            ).execute()

        # Log activity
        client.table("user_activities").insert(
            {
                "id": str(uuid4()),
                "user_id": user_id,
                "activity_type": "course_completed",
                "description": f"Curso {course.get('title', '')} completo",
                "points": 100,
            }
        ).execute()

    return {
        "course_id": course_id,
        "user_id": user_id,
        "progress_percent": 100.0,
        "completed_contents": total_contents,
        "total_contents": total_contents,
        "already_completed": already_completed,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SESSION REVIEW (professor <-> aluno)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/chat-sessions/{session_id}/review", tags=["Session Review"], summary="Criar review", status_code=201)
async def create_review(
    session_id: str,
    body: SessionReviewCreate,
    user: dict = Depends(require_role("TEACHER", "ADMIN")),
    client: Client = Depends(get_supabase),
):
    # SEC-ADMIN-5: only TEACHER/ADMIN may author a review. reviewer_id is always
    # derived from the authenticated token below — never from the body.
    session_res = (client.table("chat_sessions").select("id, user_id").eq("id", session_id).maybe_single().execute() or type("_R", (), {"data": None})())
    session = session_res.data
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    existing_res = (client.table("session_reviews").select("id").eq("session_id", session_id).maybe_single().execute() or type("_R", (), {"data": None})())
    if existing_res.data:
        raise HTTPException(status_code=409, detail="Review ja existe para esta sessao")

    new_id = str(uuid4())
    res = client.table("session_reviews").insert(
        {
            "id": new_id,
            "session_id": session_id,
            "reviewer_id": user["id"],
            "rating": body.rating,
            "feedback": body.feedback,
            "status": "pending_student",
        }
    ).execute()
    row = res.data[0] if res.data else {}

    # Notify student
    client.table("notifications").insert(
        {
            "id": str(uuid4()),
            "user_id": session["user_id"],
            "title": "Sessao avaliada pelo professor",
            "message": body.feedback or "Sua sessao de dialogo socratico foi avaliada.",
            "notification_type": "review",
            "link": f"/chat-sessions/{session_id}/review",
        }
    ).execute()

    return {
        "id": row.get("id", new_id),
        "session_id": session_id,
        "rating": row.get("rating", body.rating),
        "feedback": row.get("feedback", body.feedback),
        "status": row.get("status", "pending_student"),
        "created_at": row.get("created_at"),
    }


@router.get("/chat-sessions/{session_id}/review", tags=["Session Review"], summary="Ver review")
async def get_review(
    session_id: str,
    user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-ADMIN-5: the session owner reads their own review; TEACHER/ADMIN read any.
    # Authorize against the loaded session BEFORE returning the private review.
    session_res = (client.table("chat_sessions").select("id, user_id").eq("id", session_id).maybe_single().execute() or type("_R", (), {"data": None})())
    session = session_res.data
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    assert_owner_or_role(session.get("user_id"), user, "TEACHER", "ADMIN")

    res = (client.table("session_reviews").select("*").eq("session_id", session_id).maybe_single().execute() or type("_R", (), {"data": None})())
    row = res.data
    if not row:
        raise HTTPException(status_code=404, detail="Review nao encontrado")

    reviewer_res = (client.table("users").select("name").eq("id", row.get("reviewer_id", "")).maybe_single().execute() or type("_R", (), {"data": None})())
    reviewer_name = reviewer_res.data.get("name") if reviewer_res.data else None

    return {
        "id": row.get("id"),
        "session_id": session_id,
        "reviewer_id": row.get("reviewer_id"),
        "reviewer_name": reviewer_name,
        "rating": row.get("rating"),
        "feedback": row.get("feedback"),
        "student_reply": row.get("student_reply"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


@router.put("/chat-sessions/{session_id}/review", tags=["Session Review"], summary="Atualizar review")
async def update_review(
    session_id: str,
    body: SessionReviewCreate,
    _user: dict = Depends(require_role("TEACHER", "ADMIN")),
    client: Client = Depends(get_supabase),
):
    # SEC-ADMIN-5: only TEACHER/ADMIN may mutate rating/feedback (gate via require_role).
    res = (client.table("session_reviews").select("*").eq("session_id", session_id).maybe_single().execute() or type("_R", (), {"data": None})())
    row = res.data
    if not row:
        raise HTTPException(status_code=404, detail="Review nao encontrado")

    update_data: dict = {"status": "pending_student"}
    if body.rating is not None:
        update_data["rating"] = body.rating
    if body.feedback is not None:
        update_data["feedback"] = body.feedback

    updated = client.table("session_reviews").update(update_data).eq("id", row["id"]).execute()
    updated_row = updated.data[0] if updated.data else row

    return {
        "id": updated_row.get("id"),
        "rating": updated_row.get("rating"),
        "feedback": updated_row.get("feedback"),
        "status": updated_row.get("status"),
        "updated_at": updated_row.get("updated_at"),
    }


@router.post("/chat-sessions/{session_id}/review/reply", tags=["Session Review"], summary="Aluno responde review")
async def reply_review(
    session_id: str,
    body: SessionReviewReply,
    user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # SEC-ADMIN-5: only the session owner may reply. Load the session and gate
    # ownership BEFORE any update/notification — a cross actor causes no write and
    # no spurious notification (which would otherwise be attributed to the attacker).
    session_res = (client.table("chat_sessions").select("id, user_id").eq("id", session_id).maybe_single().execute() or type("_R", (), {"data": None})())
    session = session_res.data
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")
    assert_owner_or_role(session.get("user_id"), user, "ADMIN")

    res = (client.table("session_reviews").select("*").eq("session_id", session_id).maybe_single().execute() or type("_R", (), {"data": None})())
    row = res.data
    if not row:
        raise HTTPException(status_code=404, detail="Review nao encontrado")

    updated = client.table("session_reviews").update(
        {"student_reply": body.reply, "status": "replied"}
    ).eq("id", row["id"]).execute()
    updated_row = updated.data[0] if updated.data else row

    # Notify reviewer
    client.table("notifications").insert(
        {
            "id": str(uuid4()),
            "user_id": row["reviewer_id"],
            "title": "Aluno respondeu a avaliacao",
            "message": f"{user['name']} respondeu: {body.reply[:100]}",
            "notification_type": "review_reply",
            "link": f"/chat-sessions/{session_id}/review",
        }
    ).execute()

    return {
        "id": updated_row.get("id"),
        "student_reply": updated_row.get("student_reply"),
        "status": updated_row.get("status"),
    }


def _build_discipline_content_maps(client: Client, discipline_id: str) -> dict:
    """Resolve the ``content_id -> chapter -> course`` chain for a discipline.

    Shared helper mirroring the mapping the gradebook (``discipline_gradebook``)
    and the export (``export_discipline_grades``) already build inline. Returns a
    dict with:
      * ``course_titles``:   course_id -> course title
      * ``chapter_titles``:  chapter_id -> chapter title
      * ``content_titles``:  content_id -> content title
      * ``content_chapter``: content_id -> chapter_id
      * ``chapter_course``:  chapter_id -> course_id
      * ``content_ids``:     list of all content_ids under the discipline

    No server-side join exists in Supabase, so the walk is done in batched reads,
    exactly like the two existing consumers.
    """
    courses_res = client.table("courses").select("id, title").eq("discipline_id", discipline_id).execute()
    courses = courses_res.data or []
    course_titles = {c["id"]: c.get("title") for c in courses}
    course_ids = [c["id"] for c in courses]

    chapter_course: dict[str, str] = {}
    chapter_titles: dict[str, str] = {}
    if course_ids:
        chapters_res = client.table("chapters").select("id, course_id, title").in_("course_id", course_ids).execute()
        for ch in (chapters_res.data or []):
            chapter_course[ch["id"]] = ch["course_id"]
            chapter_titles[ch["id"]] = ch.get("title")

    content_chapter: dict[str, str] = {}
    content_titles: dict[str, str] = {}
    if chapter_course:
        chapter_ids = list(chapter_course.keys())
        contents_res = client.table("contents").select("id, chapter_id, title").in_("chapter_id", chapter_ids).execute()
        for ct in (contents_res.data or []):
            content_chapter[ct["id"]] = ct.get("chapter_id", "")
            content_titles[ct["id"]] = ct.get("title")

    return {
        "course_titles": course_titles,
        "chapter_titles": chapter_titles,
        "content_titles": content_titles,
        "content_chapter": content_chapter,
        "chapter_course": chapter_course,
        "content_ids": list(content_chapter.keys()),
    }


@router.get(
    "/disciplines/{discipline_id}/sessions",
    tags=["Session Review"],
    summary="Sessoes de uma disciplina",
)
async def discipline_sessions(
    discipline_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    student_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("ADMIN", "TEACHER")),
    client: Client = Depends(get_supabase),
):
    # Role gate (403 STUDENT) + teacher discipline-scoping (403 non-owner) BEFORE
    # any read of peer tutoring sessions — SEC-SCOPE-1. ADMIN bypasses scoping.
    assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))

    # Resolve the content -> chapter -> course chain (shared helper). GRD-1 also
    # surfaces course/chapter/content titles + the per-session rating so the
    # student drill-down can group by course/chapter without extra round trips.
    maps = _build_discipline_content_maps(client, discipline_id)
    content_ids = maps["content_ids"]
    if not content_ids:
        return {"data": [], "total": 0, "page": page, "per_page": per_page, "has_more": False}

    # Get chat sessions for those content IDs
    q = client.table("chat_sessions").select("*", count="exact").in_("content_id", content_ids)
    if status_filter:
        q = q.eq("status", status_filter)
    # GRD-1: optional per-student drill-down filter (additive; unfiltered path
    # unchanged for the discipline-wide "Conversas" tab).
    if student_id:
        q = q.eq("user_id", student_id)

    sessions_res = q.order("created_at", desc=True).range((page - 1) * per_page, page * per_page - 1).execute()
    total = sessions_res.count or 0
    rows = sessions_res.data or []

    # Collect user IDs and session IDs for batch lookups
    user_ids = list({s["user_id"] for s in rows if s.get("user_id")})
    session_ids = [s["id"] for s in rows]

    # Batch fetch users
    users_map: dict[str, dict] = {}
    if user_ids:
        users_res = client.table("users").select("id, name").in_("id", user_ids).execute()
        users_map = {u["id"]: u for u in (users_res.data or [])}

    # Batch fetch reviews (status + rating — rating powers the drill-down cell)
    reviews_map: dict[str, dict] = {}
    if session_ids:
        reviews_res = client.table("session_reviews").select("session_id, status, rating").in_("session_id", session_ids).execute()
        reviews_map = {r["session_id"]: r for r in (reviews_res.data or [])}

    result = []
    for s in rows:
        u = users_map.get(s.get("user_id", ""), {})
        review = reviews_map.get(s.get("id", ""))
        content_id = s.get("content_id") or ""
        chapter_id = maps["content_chapter"].get(content_id, "")
        course_id = maps["chapter_course"].get(chapter_id, "")
        result.append(
            {
                "id": s.get("id"),
                "user_id": s.get("user_id"),
                "user_name": u.get("name"),
                "content_id": s.get("content_id"),
                "content_title": maps["content_titles"].get(content_id),
                "chapter_id": chapter_id or None,
                "chapter_title": maps["chapter_titles"].get(chapter_id),
                "course_id": course_id or None,
                "course_title": maps["course_titles"].get(course_id),
                "status": s.get("status"),
                "total_messages": s.get("total_messages"),
                "performance_score": s.get("performance_score"),
                "review_status": review.get("status") if review else None,
                "rating": review.get("rating") if review else None,
                "created_at": s.get("created_at"),
            }
        )

    return {
        "data": result,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": total > page * per_page,
    }


# ═══════════════════════════════════════════════════════════════════════════
# GRADEBOOK
# ═══════════════════════════════════════════════════════════════════════════


class GradeOverride(BaseModel):
    course_id: str
    grade: float = Field(..., ge=0, le=10)


@router.get(
    "/disciplines/{discipline_id}/gradebook",
    tags=["Gradebook"],
    summary="Notas dos alunos da disciplina",
)
async def discipline_gradebook(
    discipline_id: str,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    # SEC-SCOPE-2: scope TEACHER/INSTRUCTOR to their own disciplines; ADMIN bypasses.
    # Gate runs BEFORE any gradebook read so an unlinked teacher reads nothing.
    assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))

    # Verify discipline
    disc_res = (
        client.table("disciplines")
        .select("id, name")
        .eq("id", discipline_id)
        .maybe_single()
        .execute()
        or type("_R", (), {"data": None})()
    )
    if not disc_res.data:
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")

    # Get students in discipline
    ds_res = (
        client.table("discipline_students")
        .select("student_id")
        .eq("discipline_id", discipline_id)
        .execute()
    )
    student_ids = [s["student_id"] for s in (ds_res.data or [])]
    if not student_ids:
        return {"discipline_id": discipline_id, "students": []}

    # Get user info
    users_res = client.table("users").select("id, name, ra").in_("id", student_ids).execute()
    users_map = {u["id"]: u for u in (users_res.data or [])}

    # Get courses in discipline
    courses_res = client.table("courses").select("id, title").eq("discipline_id", discipline_id).execute()
    courses = courses_res.data or []
    course_ids = [c["id"] for c in courses]

    # Get content IDs -> chapter IDs -> course mapping for session reviews
    # We need to link sessions to courses via content_id -> chapter -> course
    chapter_course_map: dict[str, str] = {}
    if course_ids:
        chapters_res = client.table("chapters").select("id, course_id").in_("course_id", course_ids).execute()
        for ch in (chapters_res.data or []):
            chapter_course_map[ch["id"]] = ch["course_id"]

    content_chapter_map: dict[str, str] = {}
    if chapter_course_map:
        chapter_ids = list(chapter_course_map.keys())
        contents_res = client.table("contents").select("id, chapter_id").in_("chapter_id", chapter_ids).execute()
        for ct in (contents_res.data or []):
            content_chapter_map[ct["id"]] = ct.get("chapter_id", "")

    # Get all sessions for these students
    sessions_res = (
        client.table("chat_sessions")
        .select("id, user_id, content_id")
        .in_("user_id", student_ids)
        .execute()
    )
    sessions = sessions_res.data or []
    session_ids = [s["id"] for s in sessions]

    # Get all reviews for these sessions
    reviews_map: dict[str, list] = {}
    if session_ids:
        reviews_res = (
            client.table("session_reviews")
            .select("session_id, rating")
            .in_("session_id", session_ids)
            .not_.is_("rating", "null")
            .execute()
        )
        for r in (reviews_res.data or []):
            reviews_map.setdefault(r["session_id"], []).append(r["rating"])

    # Get grade overrides
    overrides_map: dict[str, dict[str, float]] = {}
    try:
        overrides_res = (
            client.table("grade_overrides")
            .select("student_id, course_id, grade")
            .eq("discipline_id", discipline_id)
            .execute()
        )
        for ov in (overrides_res.data or []):
            overrides_map.setdefault(ov["student_id"], {})[ov["course_id"]] = ov["grade"]
    except Exception:
        # Table may not exist yet — graceful fallback
        pass

    # Build per-student, per-course ratings
    # Map: student_id -> course_id -> [ratings]
    student_course_ratings: dict[str, dict[str, list]] = {sid: {} for sid in student_ids}
    for sess in sessions:
        uid = sess.get("user_id")
        content_id = sess.get("content_id", "")
        chapter_id = content_chapter_map.get(content_id, "")
        course_id = chapter_course_map.get(chapter_id, "")
        if uid and course_id and course_id in course_ids:
            sess_ratings = reviews_map.get(sess["id"], [])
            student_course_ratings[uid].setdefault(course_id, []).extend(sess_ratings)

    # Assemble output
    students_out = []
    for sid in student_ids:
        u = users_map.get(sid, {})
        student_overrides = overrides_map.get(sid, {})
        course_grades = []
        all_avgs = []
        for c in courses:
            cid = c["id"]
            override = student_overrides.get(cid)
            ratings = student_course_ratings.get(sid, {}).get(cid, [])
            avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
            final_grade = override if override is not None else avg_rating
            course_grades.append({
                "course_id": cid,
                "title": c.get("title"),
                "avg_rating": avg_rating,
                "override_grade": override,
                "final_grade": final_grade,
            })
            if final_grade is not None:
                all_avgs.append(final_grade)

        overall_avg = round(sum(all_avgs) / len(all_avgs), 2) if all_avgs else None
        students_out.append({
            "id": sid,
            "name": u.get("name"),
            "ra": u.get("ra"),
            "courses": course_grades,
            "overall_avg": overall_avg,
        })

    return {"discipline_id": discipline_id, "students": students_out}


@router.put(
    "/disciplines/{discipline_id}/students/{student_id}/grade",
    tags=["Gradebook"],
    summary="Definir nota manual para aluno em curso",
)
async def set_student_grade(
    discipline_id: str,
    student_id: str,
    body: GradeOverride,
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    # SEC-SCOPE-2: scope TEACHER/INSTRUCTOR to their own disciplines; ADMIN bypasses.
    # 403 fires BEFORE any read or write to grade_overrides — no partial mutation,
    # identity derived from current_user, never from the body.
    assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))

    # Verify discipline exists
    disc_res = (
        client.table("disciplines")
        .select("id")
        .eq("id", discipline_id)
        .maybe_single()
        .execute()
        or type("_R", (), {"data": None})()
    )
    if not disc_res.data:
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")

    # Verify student is enrolled
    enroll_res = (
        client.table("discipline_students")
        .select("id")
        .eq("discipline_id", discipline_id)
        .eq("student_id", student_id)
        .maybe_single()
        .execute()
        or type("_R", (), {"data": None})()
    )
    if not enroll_res.data:
        raise HTTPException(status_code=404, detail="Aluno nao esta matriculado nesta disciplina")

    # Upsert grade override
    try:
        existing = (
            client.table("grade_overrides")
            .select("id")
            .eq("discipline_id", discipline_id)
            .eq("student_id", student_id)
            .eq("course_id", body.course_id)
            .maybe_single()
            .execute()
            or type("_R", (), {"data": None})()
        )
        if existing.data:
            client.table("grade_overrides").update(
                {"grade": body.grade}
            ).eq("id", existing.data["id"]).execute()
        else:
            client.table("grade_overrides").insert({
                "id": str(uuid4()),
                "discipline_id": discipline_id,
                "student_id": student_id,
                "course_id": body.course_id,
                "grade": body.grade,
                "graded_by": current_user["id"],
            }).execute()
    except Exception as e:
        # If table doesn't exist, create it on the fly won't work with Supabase
        # Return a helpful error
        logger.error(f"Grade override error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Erro ao salvar nota. Verifique se a tabela grade_overrides existe no banco.",
        )

    return {
        "discipline_id": discipline_id,
        "student_id": student_id,
        "course_id": body.course_id,
        "grade": body.grade,
    }


# ═══════════════════════════════════════════════════════════════════════════
# GRADES EXPORT (INT-MOODLE-1 follow-up) — grades surfaced via a plain API
# endpoint (JSON/CSV). No external delivery: the Moodle export stays a stub
# (see ``IntegrationService.export_sessions_to_moodle``); this is the honest,
# read-only surface for "get the real grades out" today.
# ═══════════════════════════════════════════════════════════════════════════
@router.get(
    "/disciplines/{discipline_id}/grades/export",
    tags=["Gradebook"],
    summary="Exportar notas dos alunos da disciplina (JSON ou CSV)",
)
async def export_discipline_grades(
    discipline_id: str,
    format: str = Query("json", regex="^(json|csv)$"),
    current_user: dict = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    client: Client = Depends(get_supabase),
):
    from fastapi.responses import StreamingResponse

    # SEC-SCOPE-2 pattern: scope TEACHER/INSTRUCTOR to their own discipline;
    # ADMIN bypasses. The gate runs BEFORE any read, mirroring the gradebook
    # endpoint immediately above.
    assert_teacher_owns_discipline(discipline_id, current_user, DisciplineRepository(client))

    # Verify discipline exists.
    disc_res = (
        client.table("disciplines")
        .select("id, name")
        .eq("id", discipline_id)
        .maybe_single()
        .execute()
        or type("_R", (), {"data": None})()
    )
    if not disc_res.data:
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")

    # Students enrolled in the discipline.
    ds_res = (
        client.table("discipline_students")
        .select("student_id")
        .eq("discipline_id", discipline_id)
        .execute()
    )
    student_ids = [s["student_id"] for s in (ds_res.data or [])]

    rows_out: List[dict] = []
    if student_ids:
        # Batch-fetch users (name, ra/email).
        users_res = client.table("users").select("id, name, ra, email").in_("id", student_ids).execute()
        users_map = {u["id"]: u for u in (users_res.data or [])}

        # Scope sessions to the discipline's own content (same content_id ->
        # chapter -> course chain as the gradebook endpoint above, mirrored
        # here to close a cross-discipline leak: a student enrolled in
        # discipline A and B would otherwise have discipline B's sessions
        # show up in discipline A's export via the unscoped user_id filter).
        courses_res = client.table("courses").select("id").eq("discipline_id", discipline_id).execute()
        course_ids = [c["id"] for c in (courses_res.data or [])]

        chapter_course_map: dict[str, str] = {}
        if course_ids:
            chapters_res = client.table("chapters").select("id, course_id").in_("course_id", course_ids).execute()
            for ch in (chapters_res.data or []):
                chapter_course_map[ch["id"]] = ch["course_id"]

        content_chapter_map: dict[str, str] = {}
        if chapter_course_map:
            chapter_ids = list(chapter_course_map.keys())
            contents_for_scope_res = (
                client.table("contents").select("id, chapter_id").in_("chapter_id", chapter_ids).execute()
            )
            for ct in (contents_for_scope_res.data or []):
                content_chapter_map[ct["id"]] = ct.get("chapter_id", "")

        discipline_content_ids = set(content_chapter_map.keys())

        # Sessions for those students (content_id links to content -> chapter -> course,
        # but the export is per-session, so course/chapter context is not surfaced in the
        # row shape — mirrors the gradebook's own session shape, just one row per session
        # instead of per-course aggregate). Filtered down to the discipline's own content
        # below since Supabase has no server-side join here.
        sessions_res = (
            client.table("chat_sessions")
            .select("id, user_id, content_id, status, started_at, completed_at, created_at, "
                    "interactions_used, performance_score")
            .in_("user_id", student_ids)
            .execute()
        )
        sessions = [
            s for s in (sessions_res.data or [])
            if s.get("content_id") in discipline_content_ids
        ]
        session_ids = [s["id"] for s in sessions]

        # Content titles (best-effort — content_id may be null/removed).
        content_ids = list({s["content_id"] for s in sessions if s.get("content_id")})
        contents_map: dict[str, dict] = {}
        if content_ids:
            contents_res = client.table("contents").select("id, title").in_("id", content_ids).execute()
            contents_map = {c["id"]: c for c in (contents_res.data or [])}

        # Reviews (teacher rating) keyed by session_id.
        reviews_map: dict[str, dict] = {}
        if session_ids:
            reviews_res = (
                client.table("session_reviews")
                .select("session_id, rating")
                .in_("session_id", session_ids)
                .execute()
            )
            reviews_map = {r["session_id"]: r for r in (reviews_res.data or [])}

        # Grade overrides keyed by (student_id, course_id) — best-effort, table may
        # not exist yet on older environments (same graceful fallback as the
        # gradebook endpoint above).
        overrides_by_student: dict[str, dict[str, float]] = {}
        try:
            overrides_res = (
                client.table("grade_overrides")
                .select("student_id, course_id, grade")
                .eq("discipline_id", discipline_id)
                .execute()
            )
            for ov in (overrides_res.data or []):
                overrides_by_student.setdefault(ov["student_id"], {})[ov["course_id"]] = ov["grade"]
        except Exception:
            pass

        for s in sessions:
            uid = s.get("user_id")
            u = users_map.get(uid, {})
            content = contents_map.get(s.get("content_id") or "", {})
            review = reviews_map.get(s["id"])
            # started_at: real column when present, else created_at (same honest
            # fallback as prepare_moodle_export — INT-MOODLE-1).
            started_at = s.get("started_at") or s.get("created_at")
            override_grade = None
            student_overrides = overrides_by_student.get(uid)
            if student_overrides:
                # A session has no course_id directly; grade_overrides are keyed by
                # course, so we surface the override only if the student has exactly
                # one (unambiguous) override on record for this discipline.
                if len(student_overrides) == 1:
                    override_grade = next(iter(student_overrides.values()))

            rows_out.append({
                "student_id": uid,
                "student_name": u.get("name"),
                "ra": u.get("ra"),
                "email": u.get("email"),
                "content_id": s.get("content_id"),
                "content_title": content.get("title"),
                "session_status": s.get("status"),
                "started_at": started_at,
                "completed_at": s.get("completed_at"),
                "interactions_used": s.get("interactions_used"),
                "performance_score": s.get("performance_score"),
                "review_rating": review.get("rating") if review else None,
                "grade_override": override_grade,
            })

    if format == "csv":
        buf = io.StringIO()
        header = [
            "student_id", "student_name", "ra", "email", "content_id", "content_title",
            "session_status", "started_at", "completed_at", "interactions_used",
            "performance_score", "review_rating", "grade_override",
        ]
        writer = csv.writer(buf)
        writer.writerow(header)
        for r in rows_out:
            writer.writerow([r.get(col) for col in header])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=grades-{discipline_id}.csv"},
        )

    return {"discipline_id": discipline_id, "data": rows_out}
