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
from config import get_settings
from database import get_supabase

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


def _get_or_create_settings(client: Client) -> dict:
    """Return the single settings row or create one if missing."""
    res = client.table("system_settings").select("*").limit(1).maybe_single().execute()
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
        client.table("system_settings").update(cleaned).eq("id", row_id).execute()

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
    total_res = q.order_by("created_at", desc=True).range((page - 1) * per_page, page * per_page - 1).execute()
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

    total_res = query.order_by("created_at", desc=True).range((page - 1) * per_page, page * per_page - 1).execute()
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

    res = client.table("system_backups").select("*").eq("id", backup_id).maybe_single().execute()
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
    res = client.table("system_backups").select("*").eq("id", backup_id).maybe_single().execute()
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


@router.get("/notifications/{user_id}/count", tags=["Notifications"], summary="Contagem de nao lidas")
async def notification_count(
    user_id: str,
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    res = (
        client.table("notifications")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("is_read", False)
        .execute()
    )
    return {"unread": res.count or 0}


@router.get("/notifications/{user_id}", tags=["Notifications"], summary="Listar notificacoes")
async def list_notifications(
    user_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
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


@router.put("/notifications/{notification_id}/read", tags=["Notifications"], summary="Marcar como lida")
async def mark_read(
    notification_id: str,
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    res = client.table("notifications").select("id").eq("id", notification_id).maybe_single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada")
    client.table("notifications").update({"is_read": True}).eq("id", notification_id).execute()
    return {"id": notification_id, "read": True}


@router.put("/notifications/{user_id}/read-all", tags=["Notifications"], summary="Marcar todas como lidas")
async def mark_all_read(
    user_id: str,
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # Supabase doesn't return an update count directly; update all matching rows
    client.table("notifications").update({"is_read": True}).eq("user_id", user_id).eq("is_read", False).execute()
    # Count remaining unread to confirm (should be 0)
    remaining = client.table("notifications").select("id", count="exact").eq("user_id", user_id).eq("is_read", False).execute()
    marked = (remaining.count or 0)
    return {"marked_read": "all", "remaining_unread": marked}


@router.delete("/notifications/{notification_id}", tags=["Notifications"], summary="Excluir notificacao")
async def delete_notification(
    notification_id: str,
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    res = client.table("notifications").select("id").eq("id", notification_id).maybe_single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Notificacao nao encontrada")
    client.table("notifications").delete().eq("id", notification_id).execute()
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/search", tags=["Search"], summary="Busca global")
async def global_search(
    q: str = Query(..., min_length=2, max_length=200),
    _user: dict = Depends(get_current_user),
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    total_users = (client.table("users").select("id", count="exact").execute()).count or 0
    total_courses = (client.table("courses").select("id", count="exact").execute()).count or 0
    total_disciplines = (client.table("disciplines").select("id", count="exact").execute()).count or 0
    total_sessions = (client.table("chat_sessions").select("id", count="exact").execute()).count or 0

    scored = client.table("chat_sessions").select("performance_score").not_.is_("performance_score", "null").execute()
    scores = [r["performance_score"] for r in (scored.data or []) if r.get("performance_score") is not None]
    avg_score = sum(scores) / len(scores) if scores else 0

    return {
        "total_users": total_users,
        "total_courses": total_courses,
        "total_disciplines": total_disciplines,
        "total_sessions": total_sessions,
        "avg_performance_score": round(float(avg_score), 2),
    }


@router.get("/classes/{class_id}/stats", tags=["Dashboard"], summary="Estatisticas de turma")
async def class_stats(
    class_id: str,
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    """class_id maps to a Discipline id."""
    disc_res = client.table("disciplines").select("id, name").eq("id", class_id).maybe_single().execute()
    disc = disc_res.data
    if not disc:
        raise HTTPException(status_code=404, detail="Turma nao encontrada")

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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    disc_res = client.table("disciplines").select("id, name").eq("id", discipline_id).maybe_single().execute()
    disc = disc_res.data
    if not disc:
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")

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


@router.get("/users/{user_id}/stats", tags=["Gamification"], summary="Stats do usuario")
async def user_stats(
    user_id: str,
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    res = client.table("user_stats").select("*").eq("user_id", user_id).maybe_single().execute()
    row = res.data
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


@router.get("/users/{user_id}/activities", tags=["Gamification"], summary="Atividades do usuario")
async def user_activities(
    user_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
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
                "metadata": r.get("metadata_") or r.get("metadata"),
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    new_id = str(uuid4())
    res = client.table("user_activities").insert(
        {
            "id": new_id,
            "user_id": user_id,
            "activity_type": body.activity_type,
            "description": body.description,
            "points": body.points,
            "metadata_": body.metadata_,
        }
    ).execute()
    row = res.data[0] if res.data else {}

    # Update user stats (upsert)
    stats_res = client.table("user_stats").select("*").eq("user_id", user_id).maybe_single().execute()
    if stats_res.data:
        current_points = stats_res.data.get("total_points", 0) or 0
        client.table("user_stats").update(
            {"total_points": current_points + body.points}
        ).eq("user_id", user_id).execute()
    else:
        client.table("user_stats").insert(
            {"id": str(uuid4()), "user_id": user_id, "total_points": body.points}
        ).execute()

    return {
        "id": row.get("id", new_id),
        "activity_type": row.get("activity_type", body.activity_type),
        "points": row.get("points", body.points),
        "created_at": row.get("created_at"),
    }


@router.get("/users/{user_id}/achievements", tags=["Gamification"], summary="Conquistas do usuario")
async def user_achievements(
    user_id: str,
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # Prevent duplicates
    existing_res = (
        client.table("user_achievements")
        .select("*")
        .eq("user_id", user_id)
        .eq("id", achievement_id)
        .maybe_single()
        .execute()
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
            "user_id": user_id,
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # Prevent duplicate
    existing_res = (
        client.table("certificates")
        .select("*")
        .eq("user_id", user_id)
        .eq("course_id", body.course_id)
        .maybe_single()
        .execute()
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
            "user_id": user_id,
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
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


@router.post(
    "/users/{user_id}/courses/{course_id}/complete-content/{content_id}",
    tags=["Gamification"],
    summary="Marcar conteudo como completo",
)
async def complete_content(
    user_id: str,
    course_id: str,
    content_id: str,
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # Verify content exists
    content_res = client.table("contents").select("id, title").eq("id", content_id).maybe_single().execute()
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

    # Upsert course progress
    progress_res = (
        client.table("course_progress")
        .select("*")
        .eq("user_id", user_id)
        .eq("course_id", course_id)
        .maybe_single()
        .execute()
    )
    progress = progress_res.data

    if not progress:
        new_completed = 1
        progress_percent = round(new_completed / total_contents * 100, 1) if total_contents > 0 else 0
        new_id = str(uuid4())
        client.table("course_progress").insert(
            {
                "id": new_id,
                "user_id": user_id,
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

    # Log activity
    client.table("user_activities").insert(
        {
            "id": str(uuid4()),
            "user_id": user_id,
            "activity_type": "content_completed",
            "description": f"Conteudo {content.get('title', '')} completo",
            "points": 10,
        }
    ).execute()

    return {
        "course_id": course_id,
        "content_id": content_id,
        "progress_percent": progress_percent,
        "completed_contents": completed_contents,
        "total_contents": total_contents,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SESSION REVIEW (professor <-> aluno)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/chat-sessions/{session_id}/review", tags=["Session Review"], summary="Criar review", status_code=201)
async def create_review(
    session_id: str,
    body: SessionReviewCreate,
    user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    session_res = client.table("chat_sessions").select("id, user_id").eq("id", session_id).maybe_single().execute()
    session = session_res.data
    if not session:
        raise HTTPException(status_code=404, detail="Sessao nao encontrada")

    existing_res = client.table("session_reviews").select("id").eq("session_id", session_id).maybe_single().execute()
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    res = client.table("session_reviews").select("*").eq("session_id", session_id).maybe_single().execute()
    row = res.data
    if not row:
        raise HTTPException(status_code=404, detail="Review nao encontrado")

    reviewer_res = client.table("users").select("name").eq("id", row.get("reviewer_id", "")).maybe_single().execute()
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    res = client.table("session_reviews").select("*").eq("session_id", session_id).maybe_single().execute()
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
    res = client.table("session_reviews").select("*").eq("session_id", session_id).maybe_single().execute()
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
    _user: dict = Depends(get_current_user),
    client: Client = Depends(get_supabase),
):
    # Get course IDs for this discipline
    courses_res = client.table("courses").select("id").eq("discipline_id", discipline_id).execute()
    course_ids = [c["id"] for c in (courses_res.data or [])]
    if not course_ids:
        return {"data": [], "total": 0, "page": page, "per_page": per_page, "has_more": False}

    # Get chapter IDs for those courses
    chapters_res = client.table("chapters").select("id").in_("course_id", course_ids).execute()
    chapter_ids = [ch["id"] for ch in (chapters_res.data or [])]
    if not chapter_ids:
        return {"data": [], "total": 0, "page": page, "per_page": per_page, "has_more": False}

    # Get content IDs for those chapters
    contents_res = client.table("contents").select("id").in_("chapter_id", chapter_ids).execute()
    content_ids = [c["id"] for c in (contents_res.data or [])]
    if not content_ids:
        return {"data": [], "total": 0, "page": page, "per_page": per_page, "has_more": False}

    # Get chat sessions for those content IDs
    q = client.table("chat_sessions").select("*", count="exact").in_("content_id", content_ids)
    if status_filter:
        q = q.eq("status", status_filter)

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

    # Batch fetch reviews
    reviews_map: dict[str, dict] = {}
    if session_ids:
        reviews_res = client.table("session_reviews").select("session_id, status").in_("session_id", session_ids).execute()
        reviews_map = {r["session_id"]: r for r in (reviews_res.data or [])}

    result = []
    for s in rows:
        u = users_map.get(s.get("user_id", ""), {})
        review = reviews_map.get(s.get("id", ""))
        result.append(
            {
                "id": s.get("id"),
                "user_id": s.get("user_id"),
                "user_name": u.get("name"),
                "content_id": s.get("content_id"),
                "status": s.get("status"),
                "total_messages": s.get("total_messages"),
                "performance_score": s.get("performance_score"),
                "review_status": review.get("status") if review else None,
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
