"""Storage service — local file storage for uploads."""
import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from config import get_settings

ALLOWED_EXTENSIONS = {
    # NOTE: ".doc" (legacy OLE2 binary) intentionally excluded — no parser
    # exists (python-docx only reads .docx). Rejecting at upload time is
    # more honest than silently accepting a file we can never extract text
    # from. See backend/services/text_extractor.py (status="unsupported").
    "pdf", "docx", "txt", "pptx",
    "mp4", "mov", "avi", "webm",
    "mp3", "wav", "ogg", "m4a",
    "jpg", "jpeg", "png", "gif", "webp",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def _get_base_url() -> str:
    """Return the API base URL from settings, stripping trailing slash."""
    settings = get_settings()
    base = os.getenv("API_BASE_URL", "").rstrip("/")
    if not base:
        # Fallback: derive from FRONTEND_URL by replacing the port/host
        frontend = settings.FRONTEND_URL.rstrip("/")
        if "localhost" in frontend or "127.0.0.1" in frontend:
            base = f"http://localhost:{settings.PORT}"
        else:
            # In production, uploads are served from the backend origin
            base = ""
    return base


class StorageService:
    def __init__(self):
        settings = get_settings()
        self.base_dir = Path(settings.UPLOAD_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save_file(self, file: UploadFile, subdir: str = "general") -> str:
        ext = (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Extensao '{ext}' nao permitida. Permitidas: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"Arquivo excede o limite de {MAX_FILE_SIZE // (1024 * 1024)}MB")

        dest_dir = self.base_dir / subdir
        dest_dir.mkdir(parents=True, exist_ok=True)

        safe_name = f"{uuid4().hex[:12]}_{file.filename or 'file'}"
        dest_path = dest_dir / safe_name

        with open(dest_path, "wb") as f:
            f.write(content)

        relative_path = f"/uploads/{subdir}/{safe_name}"
        base_url = _get_base_url()
        return f"{base_url}{relative_path}" if base_url else relative_path

    def get_public_url(self, filename: str, subdir: str = "general") -> str:
        relative_path = f"/uploads/{subdir}/{filename}"
        base_url = _get_base_url()
        return f"{base_url}{relative_path}" if base_url else relative_path

    def delete_file(self, path: str) -> bool:
        # Strip any base URL prefix to get the relative path
        relative = path
        for prefix in ("http://", "https://"):
            if relative.startswith(prefix):
                # Remove scheme + host
                relative = "/" + "/".join(relative.split("/")[3:])
                break
        full_path = self.base_dir / relative.lstrip("/uploads/")
        if full_path.exists():
            full_path.unlink()
            return True
        return False
