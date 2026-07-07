"""Chapter upload endpoint (`POST /chapters/{chapter_id}/upload`).

Covers three fixes bundled in the same handler:

1. `storage.save_file` raises `ValueError` (bad extension / oversize) — the
   handler must translate that into a 400 (bad extension) or 413 (oversize)
   instead of letting it bubble up as an opaque 500 via the global handler.
2. The handler now calls the structured `text_extractor.extract()` contract
   and surfaces `extraction_status` / `extraction_detail` on the response,
   only attaching `body` to the created content when status == "ok".
3. Sentry only initializes when `SENTRY_DSN` is set (covered in
   `test_sentry_init.py`, not here).
"""
from __future__ import annotations

import io

import pytest
from starlette.datastructures import Headers

from services.text_extractor import ExtractionResult


CHAPTER_ID = "chapter-1"


@pytest.fixture(autouse=True)
def _seed_chapter(fake_supabase):
    """Seed a chapter row so `ChapterRepository.get_by_id` finds it."""
    fake_supabase.seed("chapters", [{"id": CHAPTER_ID, "course_id": "course-1", "order": 1}])
    fake_supabase.seed("contents", [])


@pytest.fixture
def storage_tmp(app, tmp_path, monkeypatch):
    """Redirect the module-level `storage` singleton to a throwaway dir."""
    import main

    monkeypatch.setattr(main.storage, "base_dir", tmp_path)
    return tmp_path


def _upload(client, filename: str, content: bytes, content_type: str):
    return client.post(
        f"/chapters/{CHAPTER_ID}/upload",
        files={"file": (filename, io.BytesIO(content), content_type)},
    )


class TestUploadValidationErrors:
    """(a) ValueError from storage.save_file must not leak as a 500."""

    def test_invalid_extension_returns_400(self, client, as_teacher, storage_tmp, monkeypatch):
        import main

        async def _raise_bad_extension(file, subdir="general"):
            raise ValueError("Extensao 'exe' nao permitida. Permitidas: pdf, docx, txt")

        monkeypatch.setattr(main.storage, "save_file", _raise_bad_extension)

        resp = _upload(client, "malware.exe", b"dummy", "application/pdf")

        assert resp.status_code == 400
        assert "permitida" in resp.json()["detail"].lower()

    def test_oversize_file_returns_413(self, client, as_teacher, storage_tmp, monkeypatch):
        import main

        async def _raise_oversize(file, subdir="general"):
            raise ValueError("Arquivo excede o limite de 50MB")

        monkeypatch.setattr(main.storage, "save_file", _raise_oversize)

        resp = _upload(client, "huge.pdf", b"dummy", "application/pdf")

        assert resp.status_code == 413
        assert "excede" in resp.json()["detail"].lower()

    def test_admin_can_also_upload(self, client, as_admin, storage_tmp, monkeypatch):
        import main

        async def _raise_bad_extension(file, subdir="general"):
            raise ValueError("Extensao 'bin' nao permitida")

        monkeypatch.setattr(main.storage, "save_file", _raise_bad_extension)

        resp = _upload(client, "file.bin", b"dummy", "application/pdf")

        assert resp.status_code == 400


class TestExtractionStatusSurfaced:
    """(b) extraction_status / extraction_detail on the response, contract-driven."""

    def _patch_extract(self, monkeypatch, result: ExtractionResult):
        # main.py does `from services.text_extractor import extract` as a
        # *local* import inside the handler, so patching the source module
        # (looked up fresh on every call) is what actually takes effect.
        import services.text_extractor as text_extractor

        monkeypatch.setattr(text_extractor, "extract", lambda *a, **k: result)

    def test_extraction_ok_includes_body(self, client, as_teacher, storage_tmp, monkeypatch):
        self._patch_extract(monkeypatch, ExtractionResult(status="ok", text="# Hello\nWorld"))

        resp = _upload(client, "notes.pdf", b"%PDF-1.4 dummy", "application/pdf")

        assert resp.status_code == 200
        body = resp.json()
        assert body["extraction_status"] == "ok"
        assert body.get("body") == "# Hello\nWorld"

    def test_extraction_empty_omits_body(self, client, as_teacher, storage_tmp, monkeypatch):
        self._patch_extract(monkeypatch, ExtractionResult(status="empty"))

        resp = _upload(client, "scanned.pdf", b"%PDF-1.4 dummy", "application/pdf")

        assert resp.status_code == 200
        body = resp.json()
        assert body["extraction_status"] == "empty"
        assert not body.get("body")

    def test_extraction_unsupported_omits_body(self, client, as_teacher, storage_tmp, monkeypatch):
        self._patch_extract(
            monkeypatch,
            ExtractionResult(status="unsupported", detail="Formato nao suportado"),
        )

        resp = _upload(client, "notes.txt", b"plain text", "text/plain")

        assert resp.status_code == 200
        body = resp.json()
        assert body["extraction_status"] == "unsupported"
        assert body["extraction_detail"] == "Formato nao suportado"
        assert not body.get("body")

    def test_extraction_failed_omits_body(self, client, as_teacher, storage_tmp, monkeypatch):
        self._patch_extract(
            monkeypatch,
            ExtractionResult(status="failed", detail="corrupt file"),
        )

        resp = _upload(client, "broken.pdf", b"%PDF-1.4 dummy", "application/pdf")

        assert resp.status_code == 200
        body = resp.json()
        assert body["extraction_status"] == "failed"
        assert body["extraction_detail"] == "corrupt file"
        assert not body.get("body")

    def test_non_document_type_skips_extraction(self, client, as_teacher, storage_tmp, monkeypatch):
        """Images/video/audio never invoke extraction at all."""
        resp = _upload(client, "photo.png", b"\x89PNG dummy", "image/png")

        assert resp.status_code == 200
        body = resp.json()
        assert body["extraction_status"] is None
