"""Extract PDF tables as whole visual assets attached to nearby text chunks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import fitz

from app.config import Settings
from app.services.pdf_embedded_images import ParsedAttachedAsset

logger = logging.getLogger(__name__)

_BLOCK_OVERLAP_RATIO = 0.35
_TABLE_SUMMARY_MAX_CHARS = 4000


@dataclass(frozen=True)
class EmbeddedTable:
    page: int
    section: str | None
    bbox: tuple[float, float, float, float]
    sort_key: float
    summary: str
    png_bytes: bytes
    width: int
    height: int


def _rect_area(bbox: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _rect_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def _overlaps_table_region(
    bbox: tuple[float, float, float, float],
    table_bboxes: list[tuple[float, float, float, float]],
) -> bool:
    area = max(_rect_area(bbox), 1.0)
    for table_bbox in table_bboxes:
        overlap = _rect_intersection_area(bbox, table_bbox)
        if overlap / area >= _BLOCK_OVERLAP_RATIO:
            return True
    return False


def table_bboxes_on_page(
    tables: list[EmbeddedTable],
    page_number: int,
) -> list[tuple[float, float, float, float]]:
    return [table.bbox for table in tables if table.page == page_number]


def filter_page_blocks(
    page: fitz.Page,
    exclude_bboxes: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, str]]:
    """Return text blocks with table/figure regions removed."""
    blocks = page.get_text("blocks")
    extracted: list[tuple[float, float, str]] = []
    for block in blocks:
        if len(block) < 5:
            continue
        bbox = tuple(float(value) for value in block[:4])
        if _overlaps_table_region(bbox, exclude_bboxes):
            continue
        text = str(block[4]).strip()
        if text:
            extracted.append((float(bbox[1]), float(bbox[3]), text))
    extracted.sort(key=lambda item: (item[0], item[1]))
    return extracted


def filter_page_text(
    page: fitz.Page,
    exclude_bboxes: list[tuple[float, float, float, float]],
) -> str:
    blocks = filter_page_blocks(page, exclude_bboxes)
    if blocks:
        return "\n".join(text for _, _, text in blocks)
    return ""


def _table_summary(table: object) -> str:
    try:
        markdown = table.to_markdown().strip()
    except Exception:
        markdown = ""
    if markdown:
        return markdown[:_TABLE_SUMMARY_MAX_CHARS]
    try:
        rows = table.extract()
    except Exception:
        return ""
    lines: list[str] = []
    for row in rows or []:
        cells = [str(cell or "").strip() for cell in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)[:_TABLE_SUMMARY_MAX_CHARS]


def _render_table_png(
    page: fitz.Page,
    bbox: tuple[float, float, float, float],
    *,
    scale: float,
) -> tuple[bytes, int, int]:
    clip = fitz.Rect(bbox)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    return pixmap.tobytes("png"), pixmap.width, pixmap.height


def extract_pdf_tables(
    doc: fitz.Document,
    *,
    settings: Settings,
    section_resolver: Callable[[int, float | None], str | None],
    should_skip_page: Callable[[int], bool] | None = None,
) -> list[EmbeddedTable]:
    if not settings.pdf_extract_tables:
        return []

    tables: list[EmbeddedTable] = []
    scale = settings.pdf_table_render_scale

    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if should_skip_page and should_skip_page(page_number):
            continue

        page = doc[page_index]
        try:
            finder = page.find_tables()
        except AttributeError:
            logger.warning("PyMuPDF find_tables is unavailable; table extraction disabled")
            return tables

        for table in finder.tables:
            if table.row_count < settings.pdf_table_min_rows:
                continue
            if table.col_count < settings.pdf_table_min_cols:
                continue

            summary = _table_summary(table)
            if not summary.strip():
                continue

            bbox = tuple(float(value) for value in table.bbox)
            if _rect_area(bbox) <= 0:
                continue

            try:
                png_bytes, width, height = _render_table_png(page, bbox, scale=scale)
            except Exception:
                logger.warning(
                    "Failed to render table on page %s",
                    page_number,
                    exc_info=True,
                )
                continue

            mid_y = (bbox[1] + bbox[3]) / 2
            tables.append(
                EmbeddedTable(
                    page=page_number,
                    section=section_resolver(page_number, mid_y),
                    bbox=bbox,
                    sort_key=float(bbox[1]),
                    summary=summary,
                    png_bytes=png_bytes,
                    width=width,
                    height=height,
                )
            )

    return tables


def _chunk_layout_bbox(chunk) -> tuple[float, float, float, float] | None:
    bbox = getattr(chunk, "asset_bbox", None)
    if bbox and len(bbox) == 4:
        return tuple(float(value) for value in bbox)
    return None


def _vertical_distance(
    target_y: float,
    bbox: tuple[float, float, float, float],
) -> float:
    y0, y1 = bbox[1], bbox[3]
    if y0 <= target_y <= y1:
        return 0.0
    return min(abs(target_y - y0), abs(target_y - y1))


def _is_attach_candidate(chunk) -> bool:
    page = getattr(chunk, "page", None)
    if page is None:
        return False
    if getattr(chunk, "asset_png", None):
        return False
    return True


def _pick_nearest_chunk(table: EmbeddedTable, candidates: list) -> object | None:
    table_y = (table.bbox[1] + table.bbox[3]) / 2
    pool = [chunk for chunk in candidates if _is_attach_candidate(chunk)]
    if not pool:
        return None

    if table.section:
        section_pool = [chunk for chunk in pool if chunk.section == table.section]
        if section_pool:
            pool = section_pool

    def rank(chunk: object) -> tuple[float, int, int]:
        bbox = _chunk_layout_bbox(chunk)
        if bbox:
            distance = _vertical_distance(table_y, bbox)
            prefer_above = 0 if bbox[3] <= table_y else 1
            return (distance, prefer_above, int(getattr(chunk, "chunk_index", 0)))
        slot = int(getattr(chunk, "chunk_index", 0))
        return (float("inf"), 1, slot)

    return min(pool, key=rank)


def _table_to_attached_asset(table: EmbeddedTable) -> ParsedAttachedAsset:
    return ParsedAttachedAsset(
        asset_type="table",
        page=table.page,
        bbox=table.bbox,
        png_bytes=table.png_bytes,
        width=table.width,
        height=table.height,
        text_summary=table.summary,
    )


def attach_tables_to_chunks(
    tables: list[EmbeddedTable],
    chunks: list,
) -> list[EmbeddedTable]:
    """Attach tables to nearby text chunks; return orphans."""
    if not tables:
        return []

    by_page: dict[int, list] = {}
    for chunk in chunks:
        page = getattr(chunk, "page", None)
        if page is None:
            continue
        by_page.setdefault(int(page), []).append(chunk)

    tables_by_page: dict[int, list[EmbeddedTable]] = {}
    for table in tables:
        tables_by_page.setdefault(table.page, []).append(table)
    for page_tables in tables_by_page.values():
        page_tables.sort(key=lambda item: item.sort_key)

    orphans: list[EmbeddedTable] = []
    for page, page_tables in tables_by_page.items():
        candidates = by_page.get(page, [])
        for table in page_tables:
            target = _pick_nearest_chunk(table, candidates)
            if target is None:
                orphans.append(table)
                continue
            target.attached_assets.append(_table_to_attached_asset(table))

    return orphans
