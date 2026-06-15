import re
from collections.abc import Callable
from dataclasses import dataclass

import fitz

from app.config import Settings, get_settings
from app.services.ocr import OCRService

_HEADING_RE = re.compile(r"^第[一二三四五六七八九十百千\d]+[章节部分]|^\d+(\.\d+)*\s+\S")
_PROCEDURE_RE = re.compile(r"^(\d+[\.\)、．]|步骤\s*\d+|[①②③④⑤])")


@dataclass
class ParsedChunk:
    text: str
    page: int | None
    section: str | None
    chunk_index: int
    chunk_type: str


@dataclass
class ParseResult:
    chunks: list[ParsedChunk]
    page_count: int
    ocr_pages: int


def _detect_chunk_type(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "text"
    procedure_lines = sum(1 for line in lines if _PROCEDURE_RE.match(line))
    if procedure_lines >= 2 or (len(lines) <= 5 and procedure_lines >= 1):
        return "procedure"
    if any(keyword in text for keyword in ("注意", "警告", "危险", "WARNING", "CAUTION")):
        return "warning"
    if "|" in text and text.count("|") >= 2:
        return "table"
    return "text"


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            split_at = text.rfind("\n", start + chunk_size // 2, end)
            if split_at == -1:
                split_at = text.rfind("。", start + chunk_size // 2, end)
            if split_at == -1:
                split_at = text.rfind(". ", start + chunk_size // 2, end)
            if split_at != -1:
                end = split_at + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def _extract_native_page_text(page: fitz.Page) -> str:
    blocks = page.get_text("blocks")
    texts: list[str] = []
    for block in blocks:
        if len(block) < 5:
            continue
        text = str(block[4]).strip()
        if text:
            texts.append(text)
    if texts:
        return "\n".join(texts)
    return page.get_text().strip()


def _page_needs_ocr(native_text: str, settings: Settings) -> bool:
    if not settings.ocr_enabled:
        return False
    if settings.ocr_force:
        return True
    return len(native_text.strip()) < settings.ocr_min_chars_per_page


def _split_page_into_sections(page_text: str, page_number: int) -> list[tuple[str | None, str, int]]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    if not lines:
        return []

    sections: list[tuple[str | None, str, int]] = []
    current_section: str | None = None
    buffer: list[str] = []

    def flush_buffer() -> None:
        if buffer:
            sections.append((current_section, "\n".join(buffer).strip(), page_number))
            buffer.clear()

    for line in lines:
        if _HEADING_RE.match(line):
            flush_buffer()
            current_section = line
        buffer.append(line)
    flush_buffer()

    if not sections:
        return [(None, page_text.strip(), page_number)]
    return sections


class IngestionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.ocr = OCRService(self.settings) if self.settings.ocr_enabled else None

    def _extract_page_text(self, page: fitz.Page) -> tuple[str, bool]:
        native_text = _extract_native_page_text(page)
        if not _page_needs_ocr(native_text, self.settings):
            return native_text, False

        if self.ocr is None:
            return native_text, False

        ocr_text = self.ocr.recognize_page(page)
        if len(ocr_text.strip()) > len(native_text.strip()):
            return ocr_text, True
        return native_text, False

    def parse_pdf(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = doc.page_count
        sections: list[tuple[str | None, str, int | None]] = []
        ocr_pages = 0

        for page_index in range(page_count):
            page = doc[page_index]
            page_number = page_index + 1
            page_text, used_ocr = self._extract_page_text(page)
            if used_ocr:
                ocr_pages += 1
            if not page_text.strip():
                continue
            sections.extend(_split_page_into_sections(page_text, page_number))
            if on_page_progress is not None:
                on_page_progress(page_number, page_count)

        if not sections:
            raise ValueError("No text extracted from PDF")

        parsed_chunks: list[ParsedChunk] = []
        chunk_index = 0
        for section, section_text, page in sections:
            for piece in _split_text(
                section_text,
                self.settings.rag_chunk_size,
                self.settings.rag_chunk_overlap,
            ):
                parsed_chunks.append(
                    ParsedChunk(
                        text=piece,
                        page=page,
                        section=section,
                        chunk_index=chunk_index,
                        chunk_type=_detect_chunk_type(piece),
                    )
                )
                chunk_index += 1

        doc.close()
        return ParseResult(chunks=parsed_chunks, page_count=page_count, ocr_pages=ocr_pages)
