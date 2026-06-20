"""Extract PDF tables as whole visual assets attached to nearby text chunks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import fitz

from app.config import Settings
from app.services.pdf_attach_reading_order import attach_assets_by_reading_order
from app.services.pdf_layout_regions import layout_regions_for_asset
from app.services.table_html import table_dimensions_meet_minimum
from app.services.pdf_embedded_images import ParsedAttachedAsset
from app.services.pdf_geometry import (
    ASSET_OVERLAP_SKIP_RATIO,
    rect_area,
    rect_intersection_area,
)
from app.services.pdf_header_footer import HeaderFooterFilter
from app.services.pdf_table_header_detect import (
    discover_header_table_regions,
    find_tables_for_region,
)


logger = logging.getLogger(__name__)

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
    figure_number: str | None = None
    caption_text: str | None = None
    vlm_caption: str | None = None
    layout_regions: tuple[dict, ...] | None = None


def _overlaps_table_region(
    bbox: tuple[float, float, float, float],
    table_bboxes: list[tuple[float, float, float, float]],
) -> bool:
    area = max(rect_area(bbox), 1.0)
    for table_bbox in table_bboxes:
        overlap = rect_intersection_area(bbox, table_bbox)
        if overlap / area >= ASSET_OVERLAP_SKIP_RATIO:
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
    hf: HeaderFooterFilter | None = None,
) -> list[tuple[float, float, float, float, str]]:
    """Return text blocks with table/figure regions and header/footer removed."""
    from app.services.pdf_captions import is_caption_text
    from app.services.pdf_header_footer import should_drop_block

    blocks = page.get_text("blocks")
    extracted: list[tuple[float, float, float, float, str]] = []
    for block in blocks:
        if len(block) < 5:
            continue
        bbox = tuple(float(value) for value in block[:4])
        if _overlaps_table_region(bbox, exclude_bboxes):
            continue
        text = str(block[4]).strip()
        if not text:
            continue
        if should_drop_block(bbox, text, page, hf):
            continue
        if is_caption_text(text):
            continue
        extracted.append((bbox[0], bbox[1], bbox[2], bbox[3], text))
    extracted.sort(key=lambda item: (item[1], item[3]))
    return extracted


def filter_page_text(
    page: fitz.Page,
    exclude_bboxes: list[tuple[float, float, float, float]],
    hf: HeaderFooterFilter | None = None,
) -> str:
    blocks = filter_page_blocks(page, exclude_bboxes, hf=hf)
    if blocks:
        return "\n".join(text for *_, text in blocks)
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


def _embedded_table_from_fitz_table(
    page: fitz.Page,
    table: object,
    *,
    page_number: int,
    scale: float,
    settings: Settings,
    section_resolver: Callable[[int, float | None], str | None],
) -> EmbeddedTable | None:
    if not table_dimensions_meet_minimum(
        table.row_count,
        table.col_count,
        min_rows=settings.pdf_table_min_rows,
        min_cols=settings.pdf_table_min_cols,
    ):
        return None

    summary = _table_summary(table)
    if not summary.strip():
        return None

    bbox = tuple(float(value) for value in table.bbox)
    if rect_area(bbox) <= 0:
        return None

    try:
        png_bytes, width, height = _render_table_png(page, bbox, scale=scale)
    except Exception:
        logger.warning(
            "Failed to render table on page %s",
            page_number,
            exc_info=True,
        )
        return None

    mid_y = (bbox[1] + bbox[3]) / 2
    return EmbeddedTable(
        page=page_number,
        section=section_resolver(page_number, mid_y),
        bbox=bbox,
        sort_key=float(bbox[1]),
        summary=summary,
        png_bytes=png_bytes,
        width=width,
        height=height,
    )


def _embedded_tables_from_finder(
    page: fitz.Page,
    finder: fitz.TableFinder,
    *,
    page_number: int,
    scale: float,
    settings: Settings,
    section_resolver: Callable[[int, float | None], str | None],
    exclude_bboxes: list[tuple[float, float, float, float]] | None = None,
) -> list[EmbeddedTable]:
    tables: list[EmbeddedTable] = []
    for table in finder.tables:
        embedded = _embedded_table_from_fitz_table(
            page,
            table,
            page_number=page_number,
            scale=scale,
            settings=settings,
            section_resolver=section_resolver,
        )
        if embedded is None:
            continue
        if exclude_bboxes and _overlaps_table_region(embedded.bbox, exclude_bboxes):
            continue
        tables.append(embedded)
    return tables


def _extract_header_guided_tables(
    page: fitz.Page,
    page_number: int,
    *,
    scale: float,
    settings: Settings,
    section_resolver: Callable[[int, float | None], str | None],
    exclude_bboxes: list[tuple[float, float, float, float]] | None = None,
) -> list[EmbeddedTable]:
    tables: list[EmbeddedTable] = []
    known_bboxes = list(exclude_bboxes or [])

    for region in discover_header_table_regions(page, settings=settings):
        try:
            finder = find_tables_for_region(page, region, settings=settings)
        except Exception:
            logger.warning(
                "Header-guided find_tables failed on page %s (%s)",
                page_number,
                "/".join(region.headers),
                exc_info=True,
            )
            continue

        found = _embedded_tables_from_finder(
            page,
            finder,
            page_number=page_number,
            scale=scale,
            settings=settings,
            section_resolver=section_resolver,
            exclude_bboxes=known_bboxes,
        )
        if found:
            logger.info(
                "Header-guided table detection on page %s (%s): %s table(s)",
                page_number,
                "/".join(region.headers),
                len(found),
            )
        for table in found:
            tables.append(table)
            known_bboxes.append(table.bbox)

    return tables


def extract_tables_from_page(
    page: fitz.Page,
    page_number: int,
    *,
    settings: Settings,
    section_resolver: Callable[[int, float | None], str | None],
) -> list[EmbeddedTable]:
    if not settings.pdf_extract_tables:
        return []

    scale = settings.pdf_table_render_scale
    try:
        default_finder = page.find_tables()
    except AttributeError:
        raise AttributeError("PyMuPDF find_tables is unavailable")

    tables = _embedded_tables_from_finder(
        page,
        default_finder,
        page_number=page_number,
        scale=scale,
        settings=settings,
        section_resolver=section_resolver,
    )

    if settings.pdf_table_header_detect_enabled and not tables:
        header_tables = _extract_header_guided_tables(
            page,
            page_number,
            scale=scale,
            settings=settings,
            section_resolver=section_resolver,
            exclude_bboxes=[table.bbox for table in tables],
        )
        tables.extend(header_tables)

    return tables


def _table_to_attached_asset(table: EmbeddedTable) -> ParsedAttachedAsset:
    return ParsedAttachedAsset(
        asset_type="table",
        page=table.page,
        bbox=table.bbox,
        png_bytes=table.png_bytes,
        width=table.width,
        height=table.height,
        text_summary=table.summary,
        figure_caption=table.caption_text,
        figure_number=table.figure_number,
        vlm_caption=table.vlm_caption,
        layout_regions=layout_regions_for_asset(
            page=table.page,
            bbox=table.bbox,
            layout_regions=list(table.layout_regions) if table.layout_regions else None,
        ),
    )


def attach_tables_to_chunks(
    tables: list[EmbeddedTable],
    chunks: list,
) -> list[EmbeddedTable]:
    """Attach tables to preceding text chunks by reading order; return orphans."""
    return attach_assets_by_reading_order(
        tables,
        chunks,
        to_attached_asset=_table_to_attached_asset,
    )
