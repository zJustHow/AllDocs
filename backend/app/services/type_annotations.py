"""Extract chunk types from PDF highlight annotations."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import fitz

VALID_CHUNK_TYPES = frozenset({"text", "table"})
_HIGHLIGHT_ANNOT_TYPES = frozenset({fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_TEXT, fitz.PDF_ANNOT_FREE_TEXT})

_TYPE_LABELS: dict[str, str] = {
    "text": "text",
    "正文": "text",
    "table": "table",
    "表格": "table",
}


@dataclass(frozen=True)
class HighlightTypeRegion:
    chunk_type: str
    page: int
    text: str
    sort_key: float
    section: str | None = None
    bbox: tuple[float, float, float, float] | None = None


def normalize_chunk_type(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered in _TYPE_LABELS:
        return _TYPE_LABELS[lowered]
    if lowered in VALID_CHUNK_TYPES:
        return lowered
    for label, chunk_type in _TYPE_LABELS.items():
        if label in cleaned or label in lowered:
            return chunk_type
    return None


def _type_from_annotation_info(info: dict[str, Any]) -> str | None:
    for key in ("subject", "title", "content", "name"):
        value = info.get(key)
        if not value:
            continue
        chunk_type = normalize_chunk_type(str(value))
        if chunk_type:
            return chunk_type
    return None


def extract_pdf_highlight_regions(
    doc: fitz.Document,
    *,
    section_resolver: Callable[[int, float | None], str | None],
) -> list[HighlightTypeRegion]:
    regions: list[HighlightTypeRegion] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        page_number = page_index + 1
        annot = page.first_annot
        while annot:
            try:
                annot_type = annot.type[0] if annot.type else None
            except Exception:
                annot = annot.next
                continue
            if annot_type not in _HIGHLIGHT_ANNOT_TYPES:
                annot = annot.next
                continue
            chunk_type = _type_from_annotation_info(annot.info)
            if not chunk_type or chunk_type == "text":
                annot = annot.next
                continue
            rect = annot.rect
            text = page.get_text("text", clip=rect).strip()
            if not text:
                annot = annot.next
                continue
            mid_y = (float(rect.y0) + float(rect.y1)) / 2
            regions.append(
                HighlightTypeRegion(
                    chunk_type=chunk_type,
                    page=page_number,
                    text=re.sub(r"\n{3,}", "\n\n", text),
                    sort_key=float(rect.y0),
                    section=section_resolver(page_number, mid_y),
                    bbox=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                )
            )
            annot = annot.next
    return regions


def extract_page_text_excluding_rects(page: fitz.Page, rects: list[fitz.Rect]) -> str:
    if not rects:
        return _extract_native_page_text(page)
    blocks = page.get_text("blocks")
    parts: list[str] = []
    for block in blocks:
        if len(block) < 5:
            continue
        bbox = fitz.Rect(block[:4])
        if any(bbox.intersects(rect) for rect in rects):
            continue
        text = str(block[4]).strip()
        if text:
            parts.append(text)
    if parts:
        return "\n".join(parts)
    return ""


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


def highlight_rects_on_page(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    annot = page.first_annot
    while annot:
        try:
            annot_type = annot.type[0] if annot.type else None
        except Exception:
            annot = annot.next
            continue
        if annot_type not in _HIGHLIGHT_ANNOT_TYPES:
            annot = annot.next
            continue
        chunk_type = _type_from_annotation_info(annot.info)
        if chunk_type and chunk_type != "text":
            rects.append(annot.rect)
        annot = annot.next
    return rects
