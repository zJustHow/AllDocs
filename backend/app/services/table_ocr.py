"""Detect and structure raster tables in visual assets via PPStructure."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

import cv2
import numpy as np

from app.config import Settings, get_settings
from app.services.table_html import html_table_to_markdown, parse_html_table, table_dimensions_meet_minimum

logger = logging.getLogger(__name__)

_lock = Lock()
_table_engine = None


@dataclass(frozen=True)
class TableOCRResult:
    summary: str
    row_count: int
    col_count: int
    filled_cells: int
    score: float


def _get_table_engine(settings: Settings):
    global _table_engine
    if _table_engine is None:
        with _lock:
            if _table_engine is None:
                from paddleocr import PPStructure

                _table_engine = PPStructure(
                    show_log=False,
                    lang=settings.ocr_lang,
                    table=True,
                    layout=False,
                )
    return _table_engine


def is_table_structure_candidate(result: TableOCRResult, settings: Settings) -> bool:
    if not table_dimensions_meet_minimum(
        result.row_count,
        result.col_count,
        min_rows=settings.pdf_table_min_rows,
        min_cols=settings.pdf_table_min_cols,
    ):
        return False
    if result.filled_cells < settings.ocr_table_min_filled_cells:
        return False
    if not result.summary.strip():
        return False
    if (
        settings.ocr_table_min_score > 0
        and result.score < settings.ocr_table_min_score
    ):
        return False
    return True


class TableOCRService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def recognize_image_bytes(self, image_bytes: bytes) -> TableOCRResult | None:
        image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None

        def _run() -> list | None:
            with _lock:
                engine = _get_table_engine(self.settings)
                return engine(image)

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                items = pool.submit(_run).result(timeout=self.settings.ocr_table_timeout_seconds)
        except Exception:
            logger.warning("Raster table recognition failed", exc_info=True)
            return None

        if not items:
            return None

        table_item = next(
            (item for item in items if isinstance(item, dict) and item.get("type") == "table"),
            None,
        )
        if table_item is None:
            return None

        res = table_item.get("res") or {}
        html = str(res.get("html") or "")
        if not html.strip():
            return None

        _, row_count, col_count, filled_cells = parse_html_table(html)
        summary = html_table_to_markdown(html)
        if not summary.strip():
            return None

        score = float(table_item.get("score") or 0.0)
        return TableOCRResult(
            summary=summary,
            row_count=row_count,
            col_count=col_count,
            filled_cells=filled_cells,
            score=score,
        )
