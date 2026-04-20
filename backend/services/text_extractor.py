"""Text extraction from uploaded documents — Markdown output via pymupdf4llm."""
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger("harven")


def extract_text(file_path: str, mime_type: str = "") -> Optional[str]:
    """Extract text as Markdown from a document file."""
    try:
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf" or "pdf" in mime_type:
            return _extract_pdf_markdown(file_path)
        elif ext in (".docx",) or "wordprocessingml" in mime_type:
            return _extract_docx_markdown(file_path)
        elif ext in (".txt", ".md", ".html", ".htm", ".csv"):
            return _extract_plain(file_path)
        else:
            logger.warning(f"Unsupported file type for extraction: {ext}")
            return None
    except Exception as e:
        logger.error(f"Text extraction failed for {file_path}: {e}")
        return None


def extract_text_from_bytes(data: bytes, filename: str, mime_type: str = "") -> Optional[str]:
    """Extract text from in-memory bytes."""
    ext = Path(filename).suffix.lower() or ".bin"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return extract_text(tmp_path, mime_type)
    finally:
        os.unlink(tmp_path)


def extract_chapters_from_bytes(data: bytes, filename: str, mime_type: str = "") -> List[Dict[str, str]]:
    """Extract text and split into chapters based on headings."""
    ext = Path(filename).suffix.lower() or ".bin"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        md = extract_text(tmp_path, mime_type)
        if not md:
            return []
        return split_markdown_into_chapters(md)
    finally:
        os.unlink(tmp_path)


def split_markdown_into_chapters(md: str) -> List[Dict[str, str]]:
    """Split markdown by top-level headings (# or ##) into chapters."""
    lines = md.split("\n")
    chapters: List[Dict[str, str]] = []
    current_title = ""
    current_lines: list[str] = []

    for line in lines:
        if re.match(r"^#{1,2}\s+", line):
            if current_lines:
                body = "\n".join(current_lines).strip()
                if body:
                    chapters.append({"title": current_title or "Introdução", "body": body})
            current_title = re.sub(r"^#{1,2}\s+", "", line).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            chapters.append({"title": current_title or "Conteúdo", "body": body})

    if not chapters and md.strip():
        chapters.append({"title": "Conteúdo completo", "body": md.strip()})

    return chapters


def _extract_pdf_markdown(path: str) -> Optional[str]:
    import pymupdf4llm

    md = pymupdf4llm.to_markdown(path)
    return md.strip() if md and md.strip() else None


def _extract_docx_markdown(path: str) -> Optional[str]:
    from docx import Document

    doc = Document(path)
    lines = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name or "").lower()
        if "heading 1" in style:
            lines.append(f"# {text}")
        elif "heading 2" in style:
            lines.append(f"## {text}")
        elif "heading 3" in style:
            lines.append(f"### {text}")
        else:
            lines.append(text)
        lines.append("")
    result = "\n".join(lines)
    return result.strip() if result.strip() else None


def _extract_plain(path: str) -> Optional[str]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip() or None
