from __future__ import annotations

import csv
import html.parser
import json
import mimetypes
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from app.config import ApiSettings


SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".csv",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
TARGET_CHARS = 2200
OVERLAP_CHARS = 200


@dataclass(frozen=True)
class ParsedChunk:
    page: int | None
    section: str | None
    row_start: int | None
    row_end: int | None
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    parser: str
    text: str
    chunks: list[ParsedChunk]


def infer_mime_type(filename: str, fallback: str | None = None) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return fallback or guessed or "application/octet-stream"


def validate_upload(filename: str, size_bytes: int, settings: ApiSettings) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")
    if size_bytes <= 0:
        raise ValueError("Uploaded file is empty.")
    if size_bytes > settings.max_upload_bytes:
        raise ValueError(
            f"Uploaded file exceeds {settings.max_upload_bytes} byte limit."
        )


def parse_document_file(
    path: Path,
    *,
    filename: str,
    mime_type: str,
    settings: ApiSettings,
) -> ParsedDocument:
    suffix = Path(filename).suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return _parse_text(path, filename, settings)
    if suffix == ".json":
        return _parse_json(path, filename, settings)
    if suffix == ".csv":
        return _parse_csv(path, filename, settings)
    if suffix in {".html", ".htm"}:
        return _parse_html(path, filename, settings)
    if suffix == ".docx":
        return _parse_docx(path, filename, settings)
    if suffix == ".pdf":
        return _parse_pdf(path, filename, settings)
    raise ValueError(f"Unsupported file type for parsing: {mime_type}")


def chunks_to_records(
    chunks: list[ParsedChunk], *, file_id: str
) -> list[dict[str, Any]]:
    records = []
    for index, chunk in enumerate(chunks):
        records.append(
            {
                "id": f"chk_{uuid4().hex}",
                "file_id": file_id,
                "chunk_index": index,
                "page": chunk.page,
                "section": chunk.section,
                "row_start": chunk.row_start,
                "row_end": chunk.row_end,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "text": chunk.text,
                "token_count": _estimate_tokens(chunk.text),
                "embedding_id": None,
            }
        )
    return records


def _parse_text(path: Path, filename: str, settings: ApiSettings) -> ParsedDocument:
    text = _read_text(path, settings)
    return ParsedDocument(
        title=filename,
        parser="text",
        text=text,
        chunks=_chunk_text(text, section=_first_heading(text)),
    )


def _parse_json(path: Path, filename: str, settings: ApiSettings) -> ParsedDocument:
    raw = _read_text(path, settings)
    try:
        data = json.loads(raw)
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        text = raw
    text = _cap_text(text, settings)
    return ParsedDocument(
        title=filename,
        parser="json",
        text=text,
        chunks=_chunk_text(text, section="JSON"),
    )


def _parse_csv(path: Path, filename: str, settings: ApiSettings) -> ParsedDocument:
    raw = _read_text(path, settings)
    rows = list(csv.reader(raw.splitlines()))
    if not rows:
        raise ValueError("CSV has no rows.")

    header = rows[0]
    data_rows = rows[1:]
    summary = [
        f"CSV file: {filename}",
        f"Columns: {', '.join(header)}",
        f"Rows: {len(data_rows)}",
    ]
    chunks = [
        ParsedChunk(
            page=None,
            section="CSV summary",
            row_start=None,
            row_end=None,
            char_start=0,
            char_end=len("\n".join(summary)),
            text="\n".join(summary),
        )
    ]

    row_group_size = 50
    cursor = chunks[0].char_end
    for start in range(0, len(data_rows), row_group_size):
        group = data_rows[start : start + row_group_size]
        lines = [",".join(header)]
        lines.extend(",".join(row) for row in group)
        text = "\n".join(lines)
        chunks.append(
            ParsedChunk(
                page=None,
                section="CSV rows",
                row_start=start + 1,
                row_end=start + len(group),
                char_start=cursor,
                char_end=cursor + len(text),
                text=text,
            )
        )
        cursor += len(text)
        if len(chunks) >= settings.max_chunks_per_file:
            break

    document_text = "\n\n".join(chunk.text for chunk in chunks)
    return ParsedDocument(
        title=filename,
        parser="csv",
        text=_cap_text(document_text, settings),
        chunks=chunks[: settings.max_chunks_per_file],
    )


def _parse_html(path: Path, filename: str, settings: ApiSettings) -> ParsedDocument:
    raw = _read_text(path, settings)
    parser = _HTMLTextParser()
    parser.feed(raw)
    text = _cap_text(parser.text(), settings)
    return ParsedDocument(
        title=parser.title or filename,
        parser="html",
        text=text,
        chunks=_chunk_text(text, section=parser.title),
    )


def _parse_docx(path: Path, filename: str, settings: ApiSettings) -> ParsedDocument:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except Exception as exc:
        raise ValueError("Could not read DOCX document.xml.") from exc

    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        texts = [node.text or "" for node in paragraph.iter(f"{namespace}t")]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    text = _cap_text("\n\n".join(paragraphs), settings)
    return ParsedDocument(
        title=filename,
        parser="docx",
        text=text,
        chunks=_chunk_text(text, section=_first_heading(text)),
    )


def _parse_pdf(path: Path, filename: str, settings: ApiSettings) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("PDF parsing requires the pypdf package.") from exc

    reader = PdfReader(str(path))
    chunks: list[ParsedChunk] = []
    page_texts: list[str] = []
    cursor = 0
    for page_index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        page_texts.append(text)
        for chunk in _chunk_text(text, page=page_index, start_offset=cursor):
            chunks.append(chunk)
        cursor += len(text) + 2
        if len(chunks) >= settings.max_chunks_per_file:
            break
    if not chunks:
        raise ValueError("PDF text extraction returned no readable text.")
    document_text = _cap_text("\n\n".join(page_texts), settings)
    return ParsedDocument(
        title=filename,
        parser="pdf",
        text=document_text,
        chunks=chunks[: settings.max_chunks_per_file],
    )


def _read_text(path: Path, settings: ApiSettings) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return _cap_text(data.decode(encoding), settings)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode file as text.")


def _cap_text(text: str, settings: ApiSettings) -> str:
    cleaned = text.replace("\x00", "").strip()
    return cleaned[: settings.max_parsed_chars]


def _chunk_text(
    text: str,
    *,
    page: int | None = None,
    section: str | None = None,
    start_offset: int = 0,
) -> list[ParsedChunk]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not paragraphs:
        return []

    chunks: list[ParsedChunk] = []
    buffer: list[str] = []
    chunk_start = start_offset
    cursor = start_offset

    def flush(end_cursor: int) -> None:
        nonlocal buffer, chunk_start
        chunk_text = "\n\n".join(buffer).strip()
        if not chunk_text:
            return
        chunks.append(
            ParsedChunk(
                page=page,
                section=section,
                row_start=None,
                row_end=None,
                char_start=chunk_start,
                char_end=end_cursor,
                text=chunk_text,
            )
        )
        overlap = chunk_text[-OVERLAP_CHARS:] if len(chunk_text) > OVERLAP_CHARS else ""
        buffer = [overlap] if overlap else []
        chunk_start = max(start_offset, end_cursor - len(overlap))

    for paragraph in paragraphs:
        paragraph_start = cursor
        paragraph_end = cursor + len(paragraph)
        candidate = "\n\n".join([*buffer, paragraph]).strip()
        if buffer and len(candidate) > TARGET_CHARS:
            flush(paragraph_start)
        if not buffer:
            chunk_start = paragraph_start
        buffer.append(paragraph)
        cursor = paragraph_end + 2

    flush(cursor)
    return chunks


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:120]
    return None


class _HTMLTextParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._parts: list[str] = []

    @property
    def title(self) -> str | None:
        title = " ".join(" ".join(self._title_parts).split())
        return title or None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "br", "h1", "h2", "h3", "li"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self._title_parts.append(cleaned)
        self._parts.append(cleaned)

    def text(self) -> str:
        return "\n".join(
            line.strip() for line in " ".join(self._parts).splitlines() if line.strip()
        )
