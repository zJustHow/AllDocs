import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO

import fitz

from app.config import Settings, get_settings
from app.services.file_types import detect_file_type
from app.services.ocr import OCRService
from app.services.pdf_embedded_images import (
    EmbeddedFigure,
    ParsedAttachedAsset,
    attach_figures_to_chunks,
    extract_pdf_embedded_figures,
    figure_bboxes_on_page,
    figure_overlaps_bboxes,
)
from app.services.pdf_tables import (
    EmbeddedTable,
    extract_pdf_tables,
    attach_tables_to_chunks,
    filter_page_blocks,
    filter_page_text,
    table_bboxes_on_page,
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
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


@dataclass
class ParsedChunk:
    text: str
    page: int | None
    section: str | None
    chunk_index: int
    layout_bbox: tuple[float, float, float, float] | None = None
    asset_bbox: tuple[float, float, float, float] | None = None
    asset_png: bytes | None = None
    asset_width: int | None = None
    asset_height: int | None = None
    primary_asset_type: str | None = None
    primary_asset_summary: str = ""
    attached_assets: list[ParsedAttachedAsset] = field(default_factory=list)


@dataclass(frozen=True)
class TocEntry:
    level: int
    title: str
    start_page: int
    end_page: int
    path: str


@dataclass(frozen=True)
class TocAnchor:
    level: int
    title: str
    path: str
    page: int
    y: float
    has_y: bool = False


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


def _merge_bboxes(
    bboxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    if not bboxes:
        return None
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def _page_content_bbox(
    page: fitz.Page,
    exclude_bboxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    blocks = filter_page_blocks(page, exclude_bboxes)
    merged = _merge_bboxes([block[:4] for block in blocks])
    if merged:
        return merged
    rect = page.rect
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _group_contiguous_sections(
    pages: list[tuple[str | None, str, int, tuple[float, float, float, float] | None]],
) -> list[tuple[str | None, list[tuple[int, str, tuple[float, float, float, float] | None]]]]:
    if not pages:
        return []

    groups: list[
        tuple[str | None, list[tuple[int, str, tuple[float, float, float, float] | None]]]
    ] = []
    current_section = pages[0][0]
    current_pages: list[tuple[int, str, tuple[float, float, float, float] | None]] = [
        (pages[0][2], pages[0][1], pages[0][3])
    ]

    for section, text, page, bbox in pages[1:]:
        if section != current_section:
            groups.append((current_section, current_pages))
            current_section = section
            current_pages = []
        current_pages.append((page, text, bbox))
    groups.append((current_section, current_pages))
    return groups


def _concat_pages(
    pages: list[tuple[int, str, tuple[float, float, float, float] | None]],
    separator: str = _PAGE_SEPARATOR,
) -> tuple[str, list[tuple[int, int, tuple[float, float, float, float] | None]]]:
    spans: list[tuple[int, int, tuple[float, float, float, float] | None]] = []
    parts: list[str] = []
    offset = 0
    for index, (page, text, bbox) in enumerate(pages):
        if index > 0:
            offset += len(separator)
        spans.append((page, offset, bbox))
        parts.append(text)
        offset += len(text)
    return separator.join(parts), spans


def _page_for_offset(spans: list[tuple[int, int, tuple[float, float, float, float] | None]], offset: int) -> int:
    page = spans[0][0]
    for span_page, start, _bbox in spans:
        if start <= offset:
            page = span_page
        else:
            break
    return page


def _bbox_for_offset(
    spans: list[tuple[int, int, tuple[float, float, float, float] | None]],
    offset: int,
) -> tuple[float, float, float, float] | None:
    bbox: tuple[float, float, float, float] | None = None
    for _page, start, span_bbox in spans:
        if start <= offset:
            bbox = span_bbox
        else:
            break
    return bbox


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


def _extract_page_text_blocks(page: fitz.Page) -> list[tuple[float, float, str]]:
    blocks = page.get_text("blocks")
    extracted: list[tuple[float, float, str]] = []
    for block in blocks:
        if len(block) < 5:
            continue
        bbox = fitz.Rect(block[:4])
        text = str(block[4]).strip()
        if text:
            extracted.append((float(bbox.y0), float(bbox.y1), text))
    extracted.sort(key=lambda item: (item[0], item[1]))
    return extracted


def _segment_page_by_anchors(
    anchors: list[TocAnchor],
    page_number: int,
    blocks: list[tuple[float, float, float, float, str]],
    fallback_section: str | None,
) -> list[tuple[str | None, str, tuple[float, float, float, float] | None]]:
    if not blocks:
        return []

    segments: list[tuple[str | None, list[str], list[tuple[float, float, float, float]]]] = []
    current_section: str | None = None
    current_texts: list[str] = []
    current_bboxes: list[tuple[float, float, float, float]] = []

    for x0, y0, x1, y1, text in blocks:
        mid_y = (y0 + y1) / 2
        section = section_at_position(anchors, page_number, mid_y) or fallback_section
        block_bbox = (x0, y0, x1, y1)
        if section != current_section and current_texts:
            segments.append((current_section, current_texts, current_bboxes))
            current_texts = []
            current_bboxes = []
        current_section = section
        current_texts.append(text)
        current_bboxes.append(block_bbox)

    if current_texts:
        segments.append((current_section, current_texts, current_bboxes))

    return [
        (section, "\n".join(texts), _merge_bboxes(bboxes))
        for section, texts, bboxes in segments
        if texts
    ]


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


def _dest_to_page_y(page: fitz.Page, dest: dict) -> float | None:
    """Convert a PDF bookmark destination to MuPDF top-left Y."""
    to = dest.get("to")
    if to is None:
        return None
    try:
        if hasattr(to, "x"):
            pdf_point = fitz.Point(float(to.x), float(to.y))
        else:
            pdf_point = fitz.Point(float(to[0]), float(to[1]))
    except (TypeError, ValueError, IndexError):
        return None
    mupdf_point = pdf_point * page.transformation_matrix
    return float(mupdf_point.y)


def _parse_raw_toc(doc: fitz.Document) -> list[tuple[int, str, int, float | None]]:
    raw_toc = doc.get_toc(simple=False)
    if not raw_toc:
        return []

    parsed: list[tuple[int, str, int, float | None]] = []
    for row in raw_toc:
        level = int(row[0])
        title = str(row[1]).strip()
        page = max(1, int(row[2]))
        y: float | None = None
        dest = row[3] if len(row) > 3 else None
        if isinstance(dest, dict):
            dest_page = dest.get("page")
            if dest_page is not None and int(dest_page) >= 0:
                page = int(dest_page) + 1
            if 1 <= page <= doc.page_count:
                y = _dest_to_page_y(doc[page - 1], dest)
        parsed.append((level, title, page, y))
    return parsed


def _build_toc_paths(
    parsed: list[tuple[int, str, int, float | None]],
) -> list[tuple[int, str, int, float | None, str]]:
    path_titles: list[str] = []
    path_levels: list[int] = []
    with_paths: list[tuple[int, str, int, float | None, str]] = []
    for level, title, page, y in parsed:
        while path_levels and path_levels[-1] >= level:
            path_levels.pop()
            path_titles.pop()
        path_titles.append(title)
        path_levels.append(level)
        path = _truncate_section_path(_SECTION_PATH_SEPARATOR.join(path_titles))
        with_paths.append((level, title, page, y, path))
    return with_paths


def build_toc_anchors(doc: fitz.Document) -> list[TocAnchor]:
    parsed = _parse_raw_toc(doc)
    if not parsed:
        return []

    anchors: list[TocAnchor] = []
    for level, title, page, y, path in _build_toc_paths(parsed):
        anchors.append(
            TocAnchor(
                level=level,
                title=title,
                path=path,
                page=page,
                y=y if y is not None else 0.0,
                has_y=y is not None,
            )
        )
    return sorted(anchors, key=lambda anchor: (anchor.page, anchor.y, anchor.level))


def build_toc_entries(doc: fitz.Document) -> list[TocEntry]:
    parsed = _parse_raw_toc(doc)
    if not parsed:
        return []

    page_count = doc.page_count
    normalized: list[tuple[int, str, int, int]] = []
    for index, (level, title, page, _y) in enumerate(parsed):
        start_page = max(1, int(page))
        end_page = page_count
        for next_index in range(index + 1, len(parsed)):
            next_level, _, next_page, _ = parsed[next_index]
            if next_level <= level:
                end_page = max(start_page, int(next_page) - 1)
                break
        normalized.append((int(level), title, start_page, end_page))

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


def section_at_position(anchors: list[TocAnchor], page: int, y: float) -> str | None:
    path_titles: list[str] = []
    path_levels: list[int] = []
    for anchor in anchors:
        if (anchor.page, anchor.y) > (page, y):
            break
        while path_levels and path_levels[-1] >= anchor.level:
            path_levels.pop()
            path_titles.pop()
        path_titles.append(anchor.title)
        path_levels.append(anchor.level)
    if not path_titles:
        return None
    return _truncate_section_path(_SECTION_PATH_SEPARATOR.join(path_titles))


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


def _pages_with_bbox(
    pages: list[tuple[str | None, str, int]],
) -> list[tuple[str | None, str, int, tuple[float, float, float, float] | None]]:
    return [(section, text, page, None) for section, text, page in pages]


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


def _merge_pdf_layout_chunks(
    inline_chunks: list[tuple[int, float, ParsedChunk]],
    page_chunks: list[ParsedChunk],
) -> list[ParsedChunk]:
    ordered: list[tuple[int, float, int, ParsedChunk]] = []

    for page, sort_key, chunk in inline_chunks:
        ordered.append((page, sort_key, 0, chunk))

    for chunk in page_chunks:
        ordered.append((chunk.page or 0, float("inf"), chunk.chunk_index + 1, chunk))

    ordered.sort(key=lambda item: (item[0], item[1], item[2]))
    merged: list[ParsedChunk] = []
    for index, (_, _, _, chunk) in enumerate(ordered):
        chunk.chunk_index = index
        merged.append(chunk)
    return merged


def _orphan_figure_chunk(figure: EmbeddedFigure) -> ParsedChunk:
    """Standalone figure chunk; OCR clip text stays on asset caption, not chunk.text."""
    return ParsedChunk(
        text="",
        page=figure.page,
        section=figure.section,
        chunk_index=0,
        layout_bbox=figure.bbox,
        primary_asset_type="figure",
        primary_asset_summary=figure.text.strip(),
        asset_bbox=figure.bbox,
        asset_png=figure.png_bytes,
        asset_width=figure.width,
        asset_height=figure.height,
    )


def _orphan_table_chunk(table: EmbeddedTable) -> ParsedChunk:
    """Standalone table chunk; summary stays on asset caption, not chunk.text."""
    return ParsedChunk(
        text="",
        page=table.page,
        section=table.section,
        chunk_index=0,
        layout_bbox=table.bbox,
        primary_asset_type="table",
        primary_asset_summary=table.summary,
        asset_bbox=table.bbox,
        asset_png=table.png_bytes,
        asset_width=table.width,
        asset_height=table.height,
    )


def _build_chunks_from_pages(
    pages: list[tuple[str | None, str, int, tuple[float, float, float, float] | None]],
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
                    layout_bbox=_bbox_for_offset(page_spans, offset),
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
        toc_anchors = build_toc_anchors(doc)
        use_y_split = any(anchor.has_y for anchor in toc_anchors)

        def section_resolver(page_number: int, y: float | None = None) -> str | None:
            if y is not None and use_y_split:
                resolved = section_at_position(toc_anchors, page_number, y)
                if resolved:
                    return resolved
            return section_for_page(toc_entries, page_number)

        pages: list[tuple[str | None, str, int, tuple[float, float, float, float] | None]] = []
        ocr_pages = 0

        extracted_tables = extract_pdf_tables(
            doc,
            settings=self.settings,
            section_resolver=section_resolver,
            should_skip_page=lambda page_number: should_skip_front_matter(
                page_number, toc_entries
            ),
        )
        tables_by_page = {
            page: table_bboxes_on_page(extracted_tables, page)
            for page in {table.page for table in extracted_tables}
        }

        embedded_figures = extract_pdf_embedded_figures(
            doc,
            settings=self.settings,
            section_resolver=section_resolver,
            should_skip_page=lambda page_number: should_skip_front_matter(
                page_number, toc_entries
            ),
        )
        embedded_figures = [
            figure
            for figure in embedded_figures
            if not figure_overlaps_bboxes(
                figure, tables_by_page.get(figure.page, [])
            )
        ]
        figures_by_page = {
            page: figure_bboxes_on_page(embedded_figures, page)
            for page in {figure.page for figure in embedded_figures}
        }

        for page_index in range(page_count):
            page = doc[page_index]
            page_number = page_index + 1
            if should_skip_front_matter(page_number, toc_entries):
                continue

            fallback_section = section_for_page(toc_entries, page_number)
            exclude_bboxes = (
                tables_by_page.get(page_number, [])
                + figures_by_page.get(page_number, [])
            )

            if exclude_bboxes and not self.settings.ocr_force:
                page_text = filter_page_text(page, exclude_bboxes)
                used_ocr = False
            else:
                page_text, used_ocr = self._extract_page_text(page)
                if exclude_bboxes and page_text.strip():
                    page_text = filter_page_text(page, exclude_bboxes) or page_text

            if used_ocr:
                ocr_pages += 1
            if not page_text.strip() and not exclude_bboxes:
                continue
            if page_text.strip() and is_toc_text(page_text):
                continue

            if use_y_split and not used_ocr and page_text.strip():
                blocks = filter_page_blocks(page, exclude_bboxes)
                if blocks:
                    for section, segment_text, segment_bbox in _segment_page_by_anchors(
                        toc_anchors,
                        page_number,
                        blocks,
                        fallback_section,
                    ):
                        if segment_text.strip():
                            pages.append(
                                (section, segment_text.strip(), page_number, segment_bbox)
                            )
                elif page_text.strip():
                    pages.append(
                        (
                            fallback_section,
                            page_text.strip(),
                            page_number,
                            _page_content_bbox(page, exclude_bboxes),
                        )
                    )
            elif page_text.strip():
                pages.append(
                    (
                        fallback_section,
                        page_text.strip(),
                        page_number,
                        _page_content_bbox(page, exclude_bboxes),
                    )
                )
            if on_page_progress is not None:
                on_page_progress(page_number, page_count)

        if not pages and not embedded_figures and not extracted_tables:
            doc.close()
            raise ValueError("No text extracted from PDF")

        page_chunks = _build_chunks_from_pages(pages, self.settings) if pages else []

        orphan_tables = attach_tables_to_chunks(extracted_tables, page_chunks)

        orphan_figures = attach_figures_to_chunks(
            embedded_figures,
            page_chunks,
        )

        inline_chunks: list[tuple[int, float, ParsedChunk]] = []
        for table in orphan_tables:
            inline_chunks.append(
                (table.page, table.sort_key, _orphan_table_chunk(table))
            )
        for figure in orphan_figures:
            inline_chunks.append(
                (figure.page, figure.sort_key, _orphan_figure_chunk(figure))
            )

        parsed_chunks = (
            _merge_pdf_layout_chunks(inline_chunks, page_chunks)
            if inline_chunks
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
            chunks=_build_chunks_from_pages(_pages_with_bbox(pages), self.settings),
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
            chunks=_build_chunks_from_pages(_pages_with_bbox(pages), self.settings),
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
            chunks=_build_chunks_from_pages(_pages_with_bbox(pages), self.settings),
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
