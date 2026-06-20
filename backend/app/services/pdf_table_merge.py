"""Merge table fragments that continue across consecutive PDF pages."""

from __future__ import annotations

import logging
from dataclasses import replace

from app.config import Settings
from app.services.pdf_image_stitch import stitch_png_bytes_vertically
from app.services.pdf_layout_regions import layout_region
from app.services.table_html import markdown_table_column_count, merge_markdown_summaries
from app.services.pdf_tables import EmbeddedTable

logger = logging.getLogger(__name__)


def _table_near_page_bottom(
    bbox: tuple[float, float, float, float],
    page_height: float,
    *,
    ratio: float,
) -> bool:
    return float(bbox[3]) >= page_height * ratio


def _table_near_page_top(
    bbox: tuple[float, float, float, float],
    page_height: float,
    *,
    ratio: float,
) -> bool:
    return float(bbox[1]) <= page_height * ratio


def _figure_numbers_compatible(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return True
    return left == right


def _figure_numbers_match(left: str | None, right: str | None) -> bool:
    return bool(left and right and left == right)


def can_merge_cross_page_tables(
    left: EmbeddedTable,
    right: EmbeddedTable,
    *,
    page_heights: dict[int, float],
    settings: Settings,
) -> bool:
    if right.page != left.page + 1:
        return False
    if (left.section or None) != (right.section or None):
        return False
    if not _figure_numbers_compatible(left.figure_number, right.figure_number):
        return False

    left_height = page_heights.get(left.page)
    right_height = page_heights.get(right.page)
    if left_height is None or right_height is None:
        return False
    if not _table_near_page_bottom(
        left.bbox,
        left_height,
        ratio=settings.pdf_cross_page_table_bottom_ratio,
    ):
        return False
    if not _table_near_page_top(
        right.bbox,
        right_height,
        ratio=settings.pdf_cross_page_table_top_ratio,
    ):
        return False

    if _figure_numbers_match(left.figure_number, right.figure_number):
        return True

    left_cols = markdown_table_column_count(left.summary)
    right_cols = markdown_table_column_count(right.summary)
    if left_cols == 0 or right_cols == 0 or left_cols != right_cols:
        return False
    return True


def _stitched_table_png(
    group: list[EmbeddedTable],
    *,
    settings: Settings,
) -> tuple[bytes, int, int]:
    first = group[0]
    if len(group) == 1 or not settings.pdf_stitch_cross_page_table_png:
        return first.png_bytes, first.width, first.height

    try:
        return stitch_png_bytes_vertically(
            [table.png_bytes for table in group],
            gap=settings.pdf_cross_page_table_stitch_gap,
        )
    except Exception:
        logger.warning(
            "Failed to stitch cross-page table PNG (%s segments); using first page crop",
            len(group),
            exc_info=True,
        )
        return first.png_bytes, first.width, first.height


def _merge_table_group(group: list[EmbeddedTable], *, settings: Settings) -> EmbeddedTable:
    if len(group) == 1:
        table = group[0]
        if table.layout_regions:
            return table
        return replace(
            table,
            layout_regions=(layout_region(table.page, table.bbox),),
        )

    first = group[0]
    summary = merge_markdown_summaries([table.summary for table in group])
    figure_caption = next(
        (table.caption_text for table in reversed(group) if table.caption_text),
        first.caption_text,
    )
    figure_number = next(
        (table.figure_number for table in group if table.figure_number),
        None,
    )
    regions = tuple(layout_region(table.page, table.bbox) for table in group)
    png_bytes, width, height = _stitched_table_png(group, settings=settings)
    return EmbeddedTable(
        page=first.page,
        section=first.section,
        bbox=first.bbox,
        sort_key=first.sort_key,
        summary=summary,
        png_bytes=png_bytes,
        width=width,
        height=height,
        figure_number=figure_number,
        caption_text=figure_caption,
        layout_regions=regions,
    )


def merge_cross_page_tables(
    tables: list[EmbeddedTable],
    *,
    page_heights: dict[int, float],
    settings: Settings,
) -> list[EmbeddedTable]:
    if not tables or not settings.pdf_merge_cross_page_tables:
        return tables

    ordered = sorted(tables, key=lambda item: (item.page, item.sort_key))
    merged: list[EmbeddedTable] = []
    group = [ordered[0]]

    for table in ordered[1:]:
        if can_merge_cross_page_tables(
            group[-1],
            table,
            page_heights=page_heights,
            settings=settings,
        ):
            group.append(table)
            continue
        merged.append(_merge_table_group(group, settings=settings))
        group = [table]

    merged.append(_merge_table_group(group, settings=settings))

    if len(merged) < len(tables):
        logger.info(
            "Merged cross-page tables: %s fragments -> %s tables",
            len(tables),
            len(merged),
        )
    return merged
