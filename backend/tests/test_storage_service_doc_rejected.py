"""storage_service.save_file must reject .doc uploads (BUG-SWEEP #9 / FILE-1).

.doc (legacy OLE2 binary) has no parser (python-docx only reads .docx), so
accepting it at upload time is a silent dead end — the file gets stored but
its text is never extracted. Rejecting at save_file() is more honest than
letting it through and failing later.
"""
from __future__ import annotations

import io

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from services.storage_service import ALLOWED_EXTENSIONS, StorageService


def _make_upload_file(filename: str, content: bytes = b"dummy") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": "application/octet-stream"}),
    )


@pytest.fixture
def storage(tmp_path, monkeypatch):
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    service = StorageService()
    yield service
    get_settings.cache_clear()


class TestDocExtensionRejected:
    def test_doc_not_in_allowed_extensions(self):
        assert "doc" not in ALLOWED_EXTENSIONS

    def test_docx_still_allowed(self):
        assert "docx" in ALLOWED_EXTENSIONS

    async def test_save_file_raises_value_error_for_doc(self, storage: StorageService):
        upload = _make_upload_file("relatorio.doc")

        with pytest.raises(ValueError, match="[Ee]xtens"):
            await storage.save_file(upload)

    async def test_save_file_accepts_docx(self, storage: StorageService):
        upload = _make_upload_file("relatorio.docx")

        result = await storage.save_file(upload)

        assert result
        assert "relatorio.docx" in result

    async def test_save_file_accepts_pptx(self, storage: StorageService):
        upload = _make_upload_file("apresentacao.pptx")

        result = await storage.save_file(upload)

        assert result
        assert "apresentacao.pptx" in result
