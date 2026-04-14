"""Storage service — local file storage for uploads."""
import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from config import get_settings

ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "txt", "pptx",
    "mp4", "mov", "avi", "webm",
    "mp3", "wav", "ogg", "m4a",
    "jpg", "jpeg", "png", "gif", "webp",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


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

        return f"/uploads/{subdir}/{safe_name}"

    def get_public_url(self, filename: str, subdir: str = "general") -> str:
        return f"/uploads/{subdir}/{filename}"

    def delete_file(self, path: str) -> bool:
        full_path = self.base_dir / path.lstrip("/uploads/")
        if full_path.exists():
            full_path.unlink()
            return True
        return False
