"""Detect figure/table captions in PDF layout and pair them 1:1 with visual assets."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

import fitz

from app.services.pdf_embedded_images import EmbeddedFigure
from app.services.pdf_tables import EmbeddedTable

_CAPTION_LINE_RE = re.compile(
    r"^(?P<kind>图|表)\s*(?P<chapter>\d+)\s*[-–—]\s*(?P<num>\d+)\s*(?P<desc>.*)$"
)
_MAX_CAPTION_GAP_PT = 80.0


@dataclass(frozen=True)
class LayoutCaption:
    kind: Literal["figure", "table"]
    figure_number: str
    description: str
    full_text: str
    bbox: tuple[float, float, float, float]
    page: int


def normalize_figure_number(chapter: str, num: str) -> str:
    return f"{int(chapter)}-{int(num)}"


def parse_caption_line(line: str) -> tuple[Literal["figure", "table"], str, str, str] | None:
    stripped = line.strip()
    match = _CAPTION_LINE_RE.match(stripped)
    if not match:
        return None
    kind: Literal["figure", "table"] = "figure" if match.group("kind") == "图" else "table"
    number = normalize_figure_number(match.group("chapter"), match.group("num"))
    description = match.group("desc").strip()
    return kind, number, description, stripped


def is_caption_text(text: str) -> bool:
    """True when every non-empty line in the block is a figure/table caption."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    return parse_caption_line(lines[0]) is not None


def extract_page_captions(page: fitz.Page, page_number: int) -> list[LayoutCaption]:
    captions: list[LayoutCaption] = []
    for block in page.get_text("blocks"):
        if len(block) < 5:
            continue
        text = str(block[4]).strip()
        if not text or not is_caption_text(text):
            continue
        parsed = parse_caption_line(text.splitlines()[0].strip())
        if parsed is None:
            continue
        kind, number, description, full_text = parsed
        bbox = tuple(float(value) for value in block[:4])
        captions.append(
            LayoutCaption(
                kind=kind,
                figure_number=number,
                description=description,
                full_text=full_text,
                bbox=bbox,
                page=page_number,
            )
        )
    captions.sort(key=lambda item: item.bbox[1])
    return captions


def _horizontal_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _gap_below(
    asset_bbox: tuple[float, float, float, float],
    caption_bbox: tuple[float, float, float, float],
) -> float:
    return caption_bbox[1] - asset_bbox[3]


def _pick_asset_for_caption(
    caption: LayoutCaption,
    assets: list[EmbeddedFigure | EmbeddedTable],
    *,
    claimed: set[int],
) -> EmbeddedFigure | EmbeddedTable | None:
    best: EmbeddedFigure | EmbeddedTable | None = None
    best_gap = float("inf")
    for index, asset in enumerate(assets):
        if index in claimed:
            continue
        gap = _gap_below(asset.bbox, caption.bbox)
        if gap < 0 or gap > _MAX_CAPTION_GAP_PT:
            continue
        if _horizontal_overlap(asset.bbox, caption.bbox) <= 0:
            continue
        if gap < best_gap:
            best_gap = gap
            best = asset
    return best


def _caption_summary(caption: LayoutCaption) -> str:
    return caption.full_text


def apply_page_caption_matches(
    captions: list[LayoutCaption],
    figures: list[EmbeddedFigure],
    tables: list[EmbeddedTable],
) -> tuple[list[EmbeddedFigure], list[EmbeddedTable]]:
    claimed_figures: set[int] = set()
    claimed_tables: set[int] = set()
    updated_figures = list(figures)
    updated_tables = list(tables)

    for caption in captions:
        if caption.kind == "figure":
            pool = updated_figures
            claimed = claimed_figures
        else:
            pool = updated_tables
            claimed = claimed_tables

        match = _pick_asset_for_caption(caption, pool, claimed=claimed)
        if match is None:
            continue

        index = pool.index(match)
        claimed.add(index)
        summary = _caption_summary(caption)
        if caption.kind == "figure":
            updated_figures[index] = replace(
                match,
                figure_number=caption.figure_number,
                caption_text=summary,
            )
        else:
            updated_tables[index] = replace(
                match,
                figure_number=caption.figure_number,
                caption_text=summary,
            )

    return updated_figures, updated_tables
