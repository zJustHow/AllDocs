"""PDF page text extraction helpers."""

from __future__ import annotations

import re

import fitz

from app.config import Settings
from app.services.ingestion_chunking import block_spans_from_joined_blocks, merge_bboxes
from app.services.ingestion_types import BlockSpan, PageRow
from app.services.pdf_header_footer import HeaderFooterFilter
from app.services.pdf_tables import filter_page_blocks
from app.services.pdf_toc_types import TocAnchor
from app.services.pdf_toc import section_at_position

_TOC_LEADER_RE = re.compile(r"\.{4,}|…{2,}|·{4,}")
_TOC_ENTRY_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*)?\s*.+?"
    r"(?:\.{3,}|…{2,}|·{4,}|\s{2,})"
    r"\s*\d+\s*$"
)


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


def page_content_bbox(
    page: fitz.Page,
    exclude_bboxes: list[tuple[float, float, float, float]],
    hf: HeaderFooterFilter | None = None,
) -> tuple[float, float, float, float] | None:
    blocks = filter_page_blocks(page, exclude_bboxes, hf=hf)
    merged = merge_bboxes([block[:4] for block in blocks])
    if merged:
        return merged
    rect = page.rect
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def extract_native_page_text(
    page: fitz.Page,
    hf: HeaderFooterFilter | None = None,
) -> str:
    blocks = filter_page_blocks(page, [], hf=hf)
    if blocks:
        return "\n".join(text for *_, text in blocks)
    return ""


def segment_page_by_anchors(
    anchors: list[TocAnchor],
    page_number: int,
    blocks: list[tuple[float, float, float, float, str]],
    fallback_section: str | None,
) -> list[tuple[str | None, str, tuple[float, float, float, float] | None, list[BlockSpan]]]:
    if not blocks:
        return []

    segments: list[
        tuple[str | None, list[str], list[tuple[float, float, float, float]], list[tuple[float, float]]]
    ] = []
    current_section: str | None = None
    current_texts: list[str] = []
    current_bboxes: list[tuple[float, float, float, float]] = []
    current_bounds: list[tuple[float, float]] = []

    for x0, y0, x1, y1, text in blocks:
        mid_y = (y0 + y1) / 2
        section = section_at_position(anchors, page_number, mid_y) or fallback_section
        block_bbox = (x0, y0, x1, y1)
        if section != current_section and current_texts:
            segments.append((current_section, current_texts, current_bboxes, current_bounds))
            current_texts = []
            current_bboxes = []
            current_bounds = []
        current_section = section
        current_texts.append(text)
        current_bboxes.append(block_bbox)
        current_bounds.append((y0, y1))

    if current_texts:
        segments.append((current_section, current_texts, current_bboxes, current_bounds))

    return [
        (
            section,
            "\n".join(texts),
            merge_bboxes(bboxes),
            block_spans_from_joined_blocks(texts, bounds),
        )
        for section, texts, bboxes, bounds in segments
        if texts
    ]


def page_row_from_blocks(
    section: str | None,
    page_number: int,
    blocks: list[tuple[float, float, float, float, str]],
    layout_bbox: tuple[float, float, float, float] | None,
) -> PageRow | None:
    texts = [text for *_, text in blocks]
    if not texts:
        return None
    bounds = [(y0, y1) for _, y0, _, y1, _ in blocks]
    return (
        section,
        "\n".join(texts),
        page_number,
        layout_bbox,
        block_spans_from_joined_blocks(texts, bounds),
    )


def page_needs_ocr(native_text: str, settings: Settings) -> bool:
    if not settings.ocr_enabled:
        return False
    if settings.ocr_force:
        return True
    return len(native_text.strip()) < settings.ocr_min_chars_per_page
