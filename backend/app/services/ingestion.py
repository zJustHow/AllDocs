import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO

import fitz

from app.config import Settings, get_settings
from app.services.file_types import detect_file_type
from app.services.ocr import OCRService
from app.services.type_annotations import (
    HighlightTypeRegion,
    extract_page_text_excluding_rects,
    extract_pdf_highlight_regions,
    highlight_rects_on_page,
)

_SECTION_PATH_MAX_LEN = 512
_SECTION_PATH_SEPARATOR = " > "
_PAGE_SEPARATOR = "\n\n"
_TOC_LEADER_RE = re.compile(r"\.{4,}|…{2,}|·{4,}")
_TOC_ENTRY_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*)?\s*.+?"
    r"(?:\.{3,}|…{2,}|·{4,}|\s{2,})"
    r"\s*\d+\s*$"
)
_CHAPTER_ONE_RE = re.compile(
    r"第[一1壹]章|chapter\s*1\b",
    re.IGNORECASE,
)
_CHAPTER_TITLE_RE = re.compile(
    r"第[一二三四五六七八九十百千零两\d]+章|chapter\s+\d+",
    re.IGNORECASE,
)
_PROCEDURE_RE = re.compile(r"^(\d+[\.\)、．]|步骤\s*\d+|[①②③④⑤])")
_ALARM_CODE_RE = re.compile(
    r"(?:报警|错误|故障|alarm|error|fault|code)[^\w]{0,6}([A-Z]?\d{2,4})|"
    r"\b(?:E|ERR|ALM)[-_]?\d{2,4}\b",
    re.IGNORECASE,
)

_SYMPTOM_SECTION_RE = re.compile(
    r"故障现象|报警代码|错误代码|故障代码|异常现象|alarm\s*code|fault\s*code|error\s*code",
    re.IGNORECASE,
)
_CAUSE_SECTION_RE = re.compile(
    r"故障原因|可能原因|原因分析|产生原因|alarm\s*cause|fault\s*cause|root\s*cause",
    re.IGNORECASE,
)
_TROUBLESHOOTING_SECTION_RE = re.compile(
    r"故障排除|故障处理|排查|维修指导|处理办法|排除方法|troubleshooting|trouble\s*shooting",
    re.IGNORECASE,
)
_PRINCIPLE_SECTION_RE = re.compile(
    r"工作原理|技术说明|系统概述|结构说明|功能说明|operating\s*principle|how\s*it\s*works",
    re.IGNORECASE,
)
_CAUSE_TEXT_RE = re.compile(r"可能原因|产生原因|是由于|导致.*故障|because\s+of", re.IGNORECASE)
_TROUBLESHOOTING_TEXT_RE = re.compile(
    r"检查步骤|排除步骤|处理步骤|排查方法|解决方法|若.*仍.*无法",
    re.IGNORECASE,
)
_PRINCIPLE_TEXT_RE = re.compile(
    r"工作原理|触发条件|检测逻辑|控制逻辑|when.*trigger",
    re.IGNORECASE,
)
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class ParsedChunk:
    text: str
    page: int | None
    section: str | None
    chunk_index: int
    chunk_type: str
    content_role: str | None = None
    type_source: str = "heuristic"


@dataclass(frozen=True)
class TocEntry:
    level: int
    title: str
    start_page: int
    end_page: int
    path: str


@dataclass
class ParseResult:
    chunks: list[ParsedChunk]
    page_count: int
    ocr_pages: int
    toc_entries: list[TocEntry]


def toc_entry_to_dict(entry: TocEntry) -> dict:
    return {
        "level": entry.level,
        "title": entry.title,
        "start_page": entry.start_page,
        "end_page": entry.end_page,
        "path": entry.path,
    }


def toc_entries_from_dicts(items: list[dict]) -> list[TocEntry]:
    return [
        TocEntry(
            level=int(item["level"]),
            title=str(item["title"]),
            start_page=int(item["start_page"]),
            end_page=int(item["end_page"]),
            path=str(item["path"]),
        )
        for item in items
    ]


def is_toc_text(text: str) -> bool:
    """Detect table-of-contents style text (section title + dot leaders + page number)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    matched = 0
    for line in lines:
        if _TOC_ENTRY_RE.match(line):
            matched += 1
            continue
        if _TOC_LEADER_RE.search(line) and re.search(r"\d+\s*$", line):
            matched += 1
            continue
        if re.fullmatch(r"[\.\s·…]{4,}\s*\d+", line):
            matched += 1

    return matched >= 2 and matched / len(lines) >= 0.4


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


def _detect_content_role(section: str | None, text: str) -> str | None:
    section_text = section or ""
    if _SYMPTOM_SECTION_RE.search(section_text):
        return "symptom"
    if _CAUSE_SECTION_RE.search(section_text):
        return "cause"
    if _TROUBLESHOOTING_SECTION_RE.search(section_text):
        return "troubleshooting"
    if _PRINCIPLE_SECTION_RE.search(section_text):
        return "principle"

    if _ALARM_CODE_RE.search(text):
        return "symptom"
    if _CAUSE_TEXT_RE.search(text):
        return "cause"
    if _TROUBLESHOOTING_TEXT_RE.search(text):
        return "troubleshooting"
    if _PRINCIPLE_TEXT_RE.search(text):
        return "principle"
    return None


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


def first_chapter_start_page(entries: list[TocEntry]) -> int | None:
    """Return the PDF page where the first chapter begins, based on bookmarks."""
    if not entries:
        return None

    for entry in entries:
        if _CHAPTER_ONE_RE.search(entry.title) or _CHAPTER_ONE_RE.search(entry.path):
            return entry.start_page

    level_one = [entry for entry in entries if entry.level == 1]
    for entry in level_one:
        if _CHAPTER_TITLE_RE.search(entry.title):
            return entry.start_page

    if level_one:
        return min(entry.start_page for entry in level_one)

    return min(entry.start_page for entry in entries)


def should_skip_front_matter(page: int, toc_entries: list[TocEntry]) -> bool:
    content_start = first_chapter_start_page(toc_entries)
    return content_start is not None and page < content_start


def _decode_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode text file")


def _strip_html(raw_html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", raw_html)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _flush_text_buffer(
    pages: list[tuple[str | None, str, int]],
    section: str | None,
    buffer: list[str],
    page_number: int = 1,
) -> None:
    if not buffer:
        return
    text = "\n".join(buffer).strip()
    if text and not is_toc_text(text):
        pages.append((section, text, page_number))


def _parse_structured_text_pages(text: str, *, markdown: bool) -> list[tuple[str | None, str, int]]:
    text = text.strip()
    if not text:
        return []

    if not markdown:
        return [(None, text, 1)]

    pages: list[tuple[str | None, str, int]] = []
    section: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        match = _MD_HEADING_RE.match(line)
        if match:
            _flush_text_buffer(pages, section, buffer)
            section = match.group(2).strip()
            buffer = []
            continue
        buffer.append(line)
    _flush_text_buffer(pages, section, buffer)
    return pages if pages else [(None, text, 1)]


def _parse_docx_pages(file_bytes: bytes) -> list[tuple[str | None, str, int]]:
    from docx import Document as DocxDocument

    doc = DocxDocument(BytesIO(file_bytes))
    pages: list[tuple[str | None, str, int]] = []
    section: str | None = None
    buffer: list[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower()
        if style.startswith("heading"):
            _flush_text_buffer(pages, section, buffer)
            section = text
            buffer = []
            continue
        buffer.append(text)
    _flush_text_buffer(pages, section, buffer)

    if pages:
        return pages

    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            pages.append((section, text, 1))
    return pages


def _merge_pdf_highlight_chunks(
    highlight_regions: list[HighlightTypeRegion],
    page_chunks: list[ParsedChunk],
) -> list[ParsedChunk]:
    ordered: list[tuple[int, float, int, ParsedChunk]] = []

    for region in highlight_regions:
        ordered.append(
            (
                region.page,
                region.sort_key,
                0,
                ParsedChunk(
                    text=region.text,
                    page=region.page,
                    section=region.section,
                    chunk_index=0,
                    chunk_type=region.chunk_type,
                    content_role=region.content_role
                    or _detect_content_role(region.section, region.text),
                    type_source="pdf_highlight",
                ),
            )
        )

    for chunk in page_chunks:
        ordered.append((chunk.page or 0, float("inf"), chunk.chunk_index + 1, chunk))

    ordered.sort(key=lambda item: (item[0], item[1], item[2]))
    merged: list[ParsedChunk] = []
    for index, (_, _, _, chunk) in enumerate(ordered):
        chunk.chunk_index = index
        merged.append(chunk)
    return merged


def _build_chunks_from_pages(
    pages: list[tuple[str | None, str, int]],
    settings: Settings,
) -> list[ParsedChunk]:
    parsed_chunks: list[ParsedChunk] = []
    chunk_index = 0
    for section, page_group in _group_contiguous_sections(pages):
        section_text, page_spans = _concat_pages(page_group)
        for offset, piece in _split_text_with_offsets(
            section_text,
            settings.rag_chunk_size,
            settings.rag_chunk_overlap,
        ):
            parsed_chunks.append(
                ParsedChunk(
                    text=piece,
                    page=_page_for_offset(page_spans, offset),
                    section=section,
                    chunk_index=chunk_index,
                    chunk_type=_detect_chunk_type(piece),
                    content_role=_detect_content_role(section, piece),
                    type_source="heuristic",
                )
            )
            chunk_index += 1
    return parsed_chunks


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

        def _section_for_page(page_number: int) -> str | None:
            return section_for_page(toc_entries, page_number)

        highlight_regions = extract_pdf_highlight_regions(
            doc,
            section_for_page=_section_for_page,
        )
        pages: list[tuple[str | None, str, int]] = []
        ocr_pages = 0

        for page_index in range(page_count):
            page = doc[page_index]
            page_number = page_index + 1
            if should_skip_front_matter(page_number, toc_entries):
                continue

            section = _section_for_page(page_number)
            page_highlights = [region for region in highlight_regions if region.page == page_number]
            highlight_rects = highlight_rects_on_page(page) if page_highlights else []
            if highlight_rects:
                page_text = extract_page_text_excluding_rects(page, highlight_rects)
                used_ocr = False
            else:
                page_text, used_ocr = self._extract_page_text(page)

            if used_ocr:
                ocr_pages += 1
            if not page_text.strip():
                continue
            if is_toc_text(page_text):
                continue
            pages.append((section, page_text.strip(), page_number))
            if on_page_progress is not None:
                on_page_progress(page_number, page_count)

        if not pages and not highlight_regions:
            doc.close()
            raise ValueError("No text extracted from PDF")

        page_chunks = _build_chunks_from_pages(pages, self.settings)
        parsed_chunks = (
            _merge_pdf_highlight_chunks(highlight_regions, page_chunks)
            if highlight_regions
            else page_chunks
        )

        doc.close()
        return ParseResult(
            chunks=parsed_chunks,
            page_count=page_count,
            ocr_pages=ocr_pages,
            toc_entries=toc_entries,
        )

    def _parse_text_document(
        self,
        file_bytes: bytes,
        *,
        markdown: bool,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        pages = _parse_structured_text_pages(_decode_text_bytes(file_bytes), markdown=markdown)
        if not pages:
            raise ValueError("No text extracted from file")
        if on_page_progress is not None:
            on_page_progress(1, 1)
        return ParseResult(
            chunks=_build_chunks_from_pages(pages, self.settings),
            page_count=1,
            ocr_pages=0,
            toc_entries=[],
        )

    def _parse_html_document(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        text = _strip_html(_decode_text_bytes(file_bytes))
        if not text:
            raise ValueError("No text extracted from HTML")
        pages = [(None, text, 1)]
        if on_page_progress is not None:
            on_page_progress(1, 1)
        return ParseResult(
            chunks=_build_chunks_from_pages(pages, self.settings),
            page_count=1,
            ocr_pages=0,
            toc_entries=[],
        )

    def _parse_docx_document(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        pages = _parse_docx_pages(file_bytes)
        if not pages:
            raise ValueError("No text extracted from Word document")
        if on_page_progress is not None:
            on_page_progress(1, 1)
        return ParseResult(
            chunks=_build_chunks_from_pages(pages, self.settings),
            page_count=1,
            ocr_pages=0,
            toc_entries=[],
        )

    def _parse_image_document(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        if self.ocr is None:
            raise ValueError("OCR is disabled; cannot process image files")
        text = self.ocr.recognize_bytes(file_bytes).strip()
        if not text:
            raise ValueError("No text extracted from image")
        pages = [(None, text, 1)]
        if on_page_progress is not None:
            on_page_progress(1, 1)
        return ParseResult(
            chunks=_build_chunks_from_pages(pages, self.settings),
            page_count=1,
            ocr_pages=1,
            toc_entries=[],
        )

    def parse_document(
        self,
        file_bytes: bytes,
        filename: str,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        file_type = detect_file_type(filename)
        if file_type is None:
            raise ValueError(f"Unsupported file type: {filename}")

        match file_type.extension:
            case ".pdf":
                return self.parse_pdf(file_bytes, on_page_progress=on_page_progress)
            case ".docx":
                return self._parse_docx_document(file_bytes, on_page_progress=on_page_progress)
            case ".txt":
                return self._parse_text_document(
                    file_bytes, markdown=False, on_page_progress=on_page_progress
                )
            case ".md":
                return self._parse_text_document(
                    file_bytes, markdown=True, on_page_progress=on_page_progress
                )
            case ".html" | ".htm":
                return self._parse_html_document(file_bytes, on_page_progress=on_page_progress)
            case ".png" | ".jpg" | ".jpeg" | ".webp":
                return self._parse_image_document(file_bytes, on_page_progress=on_page_progress)
            case _:
                raise ValueError(f"Unsupported file type: {filename}")
