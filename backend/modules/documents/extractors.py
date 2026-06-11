"""Text extraction from library files for knowledge indexing.

Text-like formats are decoded directly; PDF support activates when the
optional ``pypdf`` package is installed (guarded import — the core stays
dependency-free).
"""

from __future__ import annotations

import re
from pathlib import Path

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".log", ".py", ".js", ".ts", ".html", ".htm",
    ".css", ".less", ".xml", ".sql", ".sh", ".bat", ".ps1",
}
PDF_EXTENSIONS = {".pdf"}

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t]+")


class ExtractionError(Exception):
    pass


def supported_for_indexing(name: str, mime_type: str) -> bool:
    suffix = Path(name or "").suffix.lower()
    if suffix in TEXT_EXTENSIONS or suffix in PDF_EXTENSIONS:
        return True
    return str(mime_type or "").startswith("text/")


def extract_text(file_bytes: bytes, *, name: str, mime_type: str) -> str:
    suffix = Path(name or "").suffix.lower()

    if suffix in PDF_EXTENSIONS or mime_type == "application/pdf":
        return _extract_pdf(file_bytes)

    if suffix in TEXT_EXTENSIONS or str(mime_type or "").startswith("text/"):
        text = _decode(file_bytes)
        if suffix in {".html", ".htm"}:
            text = _strip_html(text)
        return _normalize(text)

    raise ExtractionError(
        f"Unsupported file type for indexing: {suffix or mime_type or 'unknown'}"
    )


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def _strip_html(text: str) -> str:
    return _TAG_RE.sub(" ", text)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        from io import BytesIO

        from pypdf import PdfReader  # optional dependency
    except ImportError as exc:
        raise ExtractionError(
            "PDF indexing requires the optional 'pypdf' package: pip install pypdf"
        ) from exc

    reader = PdfReader(BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n\n".join(part for part in pages if part.strip())
    if not text.strip():
        raise ExtractionError("PDF contains no extractable text")
    return _normalize(text)


def split_into_chunks(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    """Paragraph-aware splitter: paragraphs are packed into chunks up to
    ``chunk_size`` characters; adjacent chunks share an ``overlap`` tail so
    facts on a boundary stay retrievable. Oversized paragraphs are split hard.
    """
    chunk_size = max(200, int(chunk_size))
    overlap = max(0, min(int(overlap), chunk_size // 2))

    paragraphs: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > chunk_size:
            paragraphs.append(paragraph[:chunk_size])
            paragraph = paragraph[chunk_size - overlap:]
        paragraphs.append(paragraph)

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        else:
            current = paragraph
    if current:
        chunks.append(current)
    return chunks
