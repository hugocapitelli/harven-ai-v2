"""Text extraction from uploaded documents (PDF, DOCX, TXT, MD, HTML)."""
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("harven")


def extract_text(file_path: str, mime_type: str = "") -> Optional[str]:
    """Extract plain text from a document file. Returns None on failure."""
    try:
        ext = Path(file_path).suffix.lower()

        if ext == ".pdf" or "pdf" in mime_type:
            return _extract_pdf(file_path)
        elif ext in (".docx",) or "wordprocessingml" in mime_type:
            return _extract_docx(file_path)
        elif ext in (".txt", ".md", ".html", ".htm", ".csv"):
            return _extract_plain(file_path)
        else:
            logger.warning(f"Unsupported file type for extraction: {ext}")
            return None
    except Exception as e:
        logger.error(f"Text extraction failed for {file_path}: {e}")
        return None


def extract_text_from_bytes(data: bytes, filename: str, mime_type: str = "") -> Optional[str]:
    """Extract text from in-memory bytes by writing to a temp file."""
    ext = Path(filename).suffix.lower() or ".bin"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return extract_text(tmp_path, mime_type)
    finally:
        os.unlink(tmp_path)


def _extract_pdf(path: str) -> Optional[str]:
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
    result = "\n\n".join(pages)
    return result if result.strip() else None


def _extract_docx(path: str) -> Optional[str]:
    from docx import Document

    doc = Document(path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    result = "\n\n".join(paragraphs)
    return result if result.strip() else None


def _extract_plain(path: str) -> Optional[str]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip() or None
