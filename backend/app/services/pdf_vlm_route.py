"""Route embedded bitmaps via VLM classification, then table OCR when needed."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import replace

from app.config import Settings
from app.services.caption import AssetVisionResult, CaptionService
from app.services.pdf_embedded_images import EmbeddedFigure
from app.services.pdf_tables import EmbeddedTable
from app.services.table_ocr import TableOCRService, is_table_structure_candidate

logger = logging.getLogger(__name__)

_TABLE_CAPTION_RE = re.compile(r"^表\s*\d", re.IGNORECASE)


def _looks_like_table_caption(caption_text: str | None) -> bool:
    if not caption_text or not caption_text.strip():
        return False
    return bool(_TABLE_CAPTION_RE.match(caption_text.strip()))


def _figure_to_raster_table(
    figure: EmbeddedFigure,
    summary: str,
    *,
    vlm_caption: str | None = None,
) -> EmbeddedTable:
    return EmbeddedTable(
        page=figure.page,
        section=figure.section,
        bbox=figure.bbox,
        sort_key=figure.sort_key,
        summary=summary,
        png_bytes=figure.png_bytes,
        width=figure.width,
        height=figure.height,
        figure_number=figure.figure_number,
        caption_text=figure.caption_text,
        vlm_caption=vlm_caption or figure.vlm_caption,
    )


def _try_promote_figure_to_table(
    figure: EmbeddedFigure,
    *,
    table_ocr: TableOCRService,
    settings: Settings,
    vlm_caption: str | None = None,
) -> EmbeddedTable | None:
    result = table_ocr.recognize_image_bytes(figure.png_bytes)
    if result is None or not is_table_structure_candidate(result, settings):
        return None
    table = _figure_to_raster_table(figure, result.summary, vlm_caption=vlm_caption)
    logger.info(
        "VLM route promoted embedded figure on page %s to raster table (%sx%s)",
        figure.page,
        result.row_count,
        result.col_count,
    )
    return table


def _route_single_figure(
    figure: EmbeddedFigure,
    *,
    caption_service: CaptionService,
    table_ocr: TableOCRService,
    settings: Settings,
) -> tuple[EmbeddedFigure | None, EmbeddedTable | None]:
    vlm_result: AssetVisionResult | None = None
    if not _looks_like_table_caption(figure.caption_text):
        vlm_result = caption_service.classify_and_describe(figure.png_bytes)
        if vlm_result is None:
            return figure, None

    is_table = _looks_like_table_caption(figure.caption_text)
    vlm_caption = vlm_result.caption if vlm_result else None
    if vlm_result is not None:
        is_table = vlm_result.kind == "table"

    if is_table:
        promoted = _try_promote_figure_to_table(
            figure,
            table_ocr=table_ocr,
            settings=settings,
            vlm_caption=vlm_caption,
        )
        if promoted is not None:
            return None, promoted
        if vlm_caption:
            return replace(figure, vlm_caption=vlm_caption), None
        return figure, None

    if vlm_caption:
        return replace(figure, vlm_caption=vlm_caption), None
    return figure, None


def route_figures_via_vlm(
    figures: list[EmbeddedFigure],
    *,
    settings: Settings,
    caption_service: CaptionService | None,
) -> tuple[list[EmbeddedFigure], list[EmbeddedTable]]:
    """Classify embedded images with VLM; run table OCR when classified as table."""
    if not settings.ingest_caption_enabled or caption_service is None or not figures:
        return figures, []

    max_per_page = max(1, settings.ingest_caption_max_per_page)
    by_page: dict[int, list[EmbeddedFigure]] = defaultdict(list)
    for figure in figures:
        by_page[figure.page].append(figure)

    remaining: list[EmbeddedFigure] = []
    promoted: list[EmbeddedTable] = []
    table_ocr = TableOCRService(settings)

    for page in sorted(by_page):
        page_figures = sorted(by_page[page], key=lambda item: item.sort_key)
        for index, figure in enumerate(page_figures):
            if index >= max_per_page:
                remaining.append(figure)
                continue
            try:
                routed_figure, routed_table = _route_single_figure(
                    figure,
                    caption_service=caption_service,
                    table_ocr=table_ocr,
                    settings=settings,
                )
            except Exception:
                logger.warning("VLM route failed for figure on page %s", page, exc_info=True)
                remaining.append(figure)
                continue
            if routed_table is not None:
                promoted.append(routed_table)
            elif routed_figure is not None:
                remaining.append(routed_figure)

    return remaining, promoted
