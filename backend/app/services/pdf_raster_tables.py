"""Promote embedded figures to raster tables when structure OCR is confident."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import Settings
from app.services.pdf_embedded_images import EmbeddedFigure
from app.services.pdf_tables import EmbeddedTable
from app.services.table_ocr import TableOCRService, is_table_structure_candidate

logger = logging.getLogger(__name__)


def figure_to_raster_table(
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


def _classify_figure(
    figure: EmbeddedFigure,
    service: TableOCRService,
    settings: Settings,
) -> tuple[EmbeddedFigure, EmbeddedTable | None]:
    result = service.recognize_image_bytes(figure.png_bytes)
    if result is None or not is_table_structure_candidate(result, settings):
        return figure, None

    promoted = figure_to_raster_table(figure, result.summary)
    logger.info(
        "Promoted embedded figure on page %s to raster table (%sx%s, %s filled cells)",
        figure.page,
        result.row_count,
        result.col_count,
        result.filled_cells,
    )
    return figure, promoted


def promote_figures_to_raster_tables(
    figures: list[EmbeddedFigure],
    *,
    settings: Settings,
    executor: ThreadPoolExecutor | None = None,
    processed: int = 0,
) -> tuple[list[EmbeddedFigure], list[EmbeddedTable], int]:
    """Classify embedded images; high-confidence tables join the table asset path."""
    if not settings.ocr_table_promote_enabled or not figures:
        return figures, [], processed

    service = TableOCRService(settings)
    max_per_doc = settings.ocr_table_promote_max_per_doc
    candidates: list[EmbeddedFigure] = []
    deferred: list[EmbeddedFigure] = []

    for figure in sorted(figures, key=lambda item: (item.page, item.sort_key)):
        if processed + len(candidates) >= max_per_doc:
            deferred.append(figure)
            continue
        candidates.append(figure)

    if not candidates:
        return figures, [], processed

    remaining: list[EmbeddedFigure] = list(deferred)
    promoted: list[EmbeddedTable] = []
    processed += len(candidates)

    if executor is None:
        for figure in candidates:
            _figure, table = _classify_figure(figure, service, settings)
            if table is None:
                remaining.append(figure)
            else:
                promoted.append(table)
        return remaining, promoted, processed

    futures = {
        executor.submit(_classify_figure, figure, service, settings): figure
        for figure in candidates
    }
    promotion_by_figure: dict[int, EmbeddedTable | None] = {}
    for future in as_completed(futures):
        figure = futures[future]
        _figure, table = future.result()
        promotion_by_figure[id(figure)] = table

    for figure in candidates:
        table = promotion_by_figure.get(id(figure))
        if table is None:
            remaining.append(figure)
        else:
            promoted.append(table)

    return remaining, promoted, processed
