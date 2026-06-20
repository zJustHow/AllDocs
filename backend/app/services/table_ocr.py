"""Detect and structure raster tables in visual assets via PPStructure."""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from threading import Lock

import cv2
import numpy as np

from app.config import Settings, get_settings
from app.services.table_html import html_table_to_markdown, parse_html_table, table_dimensions_meet_minimum

logger = logging.getLogger(__name__)

_pool_lock = Lock()
_table_process_pool: ProcessPoolExecutor | None = None

_child_table_engine = None


def _run_ppstructure_table(image: np.ndarray, lang: str) -> list | None:
    """Run PPStructure in an isolated child process (Paddle is not thread-safe)."""
    global _child_table_engine
    if _child_table_engine is None:
        from paddleocr import PPStructure

        _child_table_engine = PPStructure(
            show_log=False,
            lang=lang,
            table=True,
            layout=False,
        )
    return _child_table_engine(image)


def _get_table_process_pool() -> ProcessPoolExecutor:
    global _table_process_pool
    with _pool_lock:
        if _table_process_pool is None:
            _table_process_pool = ProcessPoolExecutor(max_workers=1)
        return _table_process_pool


def _reset_table_process_pool() -> None:
    global _table_process_pool
    with _pool_lock:
        if _table_process_pool is not None:
            _table_process_pool.shutdown(wait=False, cancel_futures=True)
            _table_process_pool = None


@dataclass(frozen=True)
class TableOCRResult:
    summary: str
    row_count: int
    col_count: int
    filled_cells: int
    score: float


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

        try:
            pool = _get_table_process_pool()
            future = pool.submit(_run_ppstructure_table, image, self.settings.ocr_lang)
            items = future.result(timeout=self.settings.ocr_table_timeout_seconds)
        except FuturesTimeoutError:
            logger.warning("Raster table recognition timed out after %.0fs", self.settings.ocr_table_timeout_seconds)
            _reset_table_process_pool()
            return None
        except Exception:
            logger.warning("Raster table recognition failed", exc_info=True)
            _reset_table_process_pool()
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
