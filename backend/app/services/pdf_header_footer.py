"""Detect and remove PDF header/footer text blocks during ingestion."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import fitz

from app.config import Settings

_HF_TEXT_RE = re.compile(r"\s+")
_PAGE_NUMBER_RE = re.compile(
    r"^(?:第\s*)?\d+\s*(?:页|/|\s|$)|"
    r"^(?:page|p\.?)\s*\d+\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HeaderFooterFilter:
    settings: Settings
    repeated_margin_texts: frozenset[str] = frozenset()


def normalize_hf_text(text: str) -> str:
    return _HF_TEXT_RE.sub(" ", text.strip())


def margin_y_bounds(page: fitz.Page, settings: Settings) -> tuple[float, float]:
    height = float(page.rect.height)
    header_max = height * settings.pdf_header_margin_ratio
    footer_min = height * (1.0 - settings.pdf_footer_margin_ratio)
    return header_max, footer_min


def block_center_y(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[1] + bbox[3]) / 2.0


def is_in_margin_zone(
    bbox: tuple[float, float, float, float],
    page: fitz.Page,
    settings: Settings,
) -> bool:
    header_max, footer_min = margin_y_bounds(page, settings)
    center_y = block_center_y(bbox)
    return center_y <= header_max or center_y >= footer_min


def is_page_number_text(text: str) -> bool:
    stripped = normalize_hf_text(text)
    if not stripped:
        return False
    if _PAGE_NUMBER_RE.match(stripped):
        return True
    if re.fullmatch(r"\d{1,4}", stripped):
        return True
    return False


def is_header_footer_block(
    bbox: tuple[float, float, float, float],
    text: str,
    page: fitz.Page,
    hf: HeaderFooterFilter | None,
) -> bool:
    if hf is None or not hf.settings.pdf_filter_header_footer:
        return False

    normalized = normalize_hf_text(text)
    if not normalized:
        return True

    if normalized in hf.repeated_margin_texts:
        return True
    return is_in_margin_zone(bbox, page, hf.settings)


def collect_repeated_margin_texts(
    doc: fitz.Document,
    settings: Settings,
    *,
    should_skip_page: Callable[[int], bool] | None = None,
) -> frozenset[str]:
    if not settings.pdf_filter_header_footer:
        return frozenset()

    counts: Counter[str] = Counter()
    page_count = 0
    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if should_skip_page and should_skip_page(page_number):
            continue
        page = doc[page_index]
        page_count += 1
        for block in page.get_text("blocks"):
            if len(block) < 5:
                continue
            bbox = tuple(float(value) for value in block[:4])
            text = normalize_hf_text(str(block[4]))
            if not text or not is_in_margin_zone(bbox, page, settings):
                continue
            if is_page_number_text(text):
                continue
            counts[text] += 1

    if page_count == 0:
        return frozenset()

    min_count = max(
        settings.pdf_hf_min_repeat_pages,
        int(page_count * settings.pdf_hf_min_repeat_ratio),
    )
    return frozenset(text for text, count in counts.items() if count >= min_count)


def build_header_footer_filter(
    doc: fitz.Document,
    settings: Settings,
    *,
    should_skip_page: Callable[[int], bool] | None = None,
) -> HeaderFooterFilter:
    repeated = collect_repeated_margin_texts(
        doc,
        settings,
        should_skip_page=should_skip_page,
    )
    return HeaderFooterFilter(settings=settings, repeated_margin_texts=repeated)


def ocr_y_in_margin(y_center: float, page_height: float, settings: Settings) -> bool:
    header_max = page_height * settings.pdf_header_margin_ratio
    footer_min = page_height * (1.0 - settings.pdf_footer_margin_ratio)
    return y_center <= header_max or y_center >= footer_min


def filter_ocr_lines(
    items: list[tuple[float, float, str]],
    page_height: float,
    hf: HeaderFooterFilter | None,
) -> list[tuple[float, float, str]]:
    if hf is None or not hf.settings.pdf_filter_header_footer:
        return items

    settings = hf.settings
    filtered: list[tuple[float, float, str]] = []
    for y_center, x_center, text in items:
        normalized = normalize_hf_text(text)
        if normalized in hf.repeated_margin_texts:
            continue
        if ocr_y_in_margin(y_center, page_height, settings):
            continue
        filtered.append((y_center, x_center, text))
    return filtered


def should_drop_block(
    bbox: tuple[float, float, float, float],
    text: str,
    page: fitz.Page,
    hf: HeaderFooterFilter | None,
) -> bool:
    return is_header_footer_block(bbox, text, page, hf)
