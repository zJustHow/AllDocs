import re
from collections.abc import Callable
from dataclasses import dataclass

import fitz

from app.config import Settings, get_settings
from app.services.ocr import OCRService

_SECTION_PATH_MAX_LEN = 512
_SECTION_PATH_SEPARATOR = " > "
_PAGE_SEPARATOR = "\n\n"
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


@dataclass(frozen=True)
class TocEntry:
    level: int
    title: str
    start_page: int
    end_page: int
    path: str


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


def _split_text_with_offsets(
    text: str, chunk_size: int, overlap: int
) -> list[tuple[int, str]]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [(0, text)]

    chunks: list[tuple[int, str]] = []
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
        piece = text[start:end].strip()
        if piece:
            chunks.append((start, piece))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _group_contiguous_sections(
    pages: list[tuple[str | None, str, int]],
) -> list[tuple[str | None, list[tuple[int, str]]]]:
    if not pages:
        return []

    groups: list[tuple[str | None, list[tuple[int, str]]]] = []
    current_section = pages[0][0]
    current_pages: list[tuple[int, str]] = [(pages[0][2], pages[0][1])]

    for section, text, page in pages[1:]:
        if section != current_section:
            groups.append((current_section, current_pages))
            current_section = section
            current_pages = []
        current_pages.append((page, text))
    groups.append((current_section, current_pages))
    return groups


def _concat_pages(
    pages: list[tuple[int, str]], separator: str = _PAGE_SEPARATOR
) -> tuple[str, list[tuple[int, int]]]:
    spans: list[tuple[int, int]] = []
    parts: list[str] = []
    offset = 0
    for index, (page, text) in enumerate(pages):
        if index > 0:
            offset += len(separator)
        spans.append((page, offset))
        parts.append(text)
        offset += len(text)
    return separator.join(parts), spans


def _page_for_offset(spans: list[tuple[int, int]], offset: int) -> int:
    page = spans[0][0]
    for span_page, start in spans:
        if start <= offset:
            page = span_page
        else:
            break
    return page


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


def _truncate_section_path(path: str) -> str:
    if len(path) <= _SECTION_PATH_MAX_LEN:
        return path
    return path[: _SECTION_PATH_MAX_LEN - 1] + "…"


def build_toc_entries(doc: fitz.Document) -> list[TocEntry]:
    raw_toc = doc.get_toc()
    if not raw_toc:
        return []

    page_count = doc.page_count
    normalized: list[tuple[int, str, int, int]] = []
    for index, (level, title, page) in enumerate(raw_toc):
        start_page = max(1, int(page))
        end_page = page_count
        for next_index in range(index + 1, len(raw_toc)):
            next_level, _, next_page = raw_toc[next_index]
            if next_level <= level:
                end_page = max(start_page, int(next_page) - 1)
                break
        normalized.append((int(level), str(title).strip(), start_page, end_page))

    path_titles: list[str] = []
    path_levels: list[int] = []
    entries: list[TocEntry] = []
    for level, title, start_page, end_page in normalized:
        while path_levels and path_levels[-1] >= level:
            path_levels.pop()
            path_titles.pop()
        path_titles.append(title)
        path_levels.append(level)
        path = _SECTION_PATH_SEPARATOR.join(path_titles)
        entries.append(
            TocEntry(
                level=level,
                title=title,
                start_page=start_page,
                end_page=end_page,
                path=_truncate_section_path(path),
            )
        )
    return entries


def section_for_page(entries: list[TocEntry], page: int) -> str | None:
    matches = [entry for entry in entries if entry.start_page <= page <= entry.end_page]
    if not matches:
        return None
    return max(matches, key=lambda entry: entry.level).path


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
        toc_entries = build_toc_entries(doc)
        pages: list[tuple[str | None, str, int]] = []
        ocr_pages = 0

        for page_index in range(page_count):
            page = doc[page_index]
            page_number = page_index + 1
            page_text, used_ocr = self._extract_page_text(page)
            if used_ocr:
                ocr_pages += 1
            if not page_text.strip():
                continue
            section = section_for_page(toc_entries, page_number)
            pages.append((section, page_text.strip(), page_number))
            if on_page_progress is not None:
                on_page_progress(page_number, page_count)

        if not pages:
            raise ValueError("No text extracted from PDF")

        parsed_chunks: list[ParsedChunk] = []
        chunk_index = 0
        for section, page_group in _group_contiguous_sections(pages):
            section_text, page_spans = _concat_pages(page_group)
            for offset, piece in _split_text_with_offsets(
                section_text,
                self.settings.rag_chunk_size,
                self.settings.rag_chunk_overlap,
            ):
                parsed_chunks.append(
                    ParsedChunk(
                        text=piece,
                        page=_page_for_offset(page_spans, offset),
                        section=section,
                        chunk_index=chunk_index,
                        chunk_type=_detect_chunk_type(piece),
                    )
                )
                chunk_index += 1

        doc.close()
        return ParseResult(chunks=parsed_chunks, page_count=page_count, ocr_pages=ocr_pages)
