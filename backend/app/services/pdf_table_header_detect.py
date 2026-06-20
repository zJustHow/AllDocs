"""Locate PDF tables via searchable header text → clip + vertical_lines for find_tables()."""

from __future__ import annotations

import re
from dataclasses import dataclass

import fitz

from app.config import Settings

_SECTION_HEADING_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?(?:\s|$)")

# Known multi-column header sets, longest / most specific first.
HEADER_SETS: tuple[tuple[str, ...], ...] = (
    ("第一级", "第二级", "功能说明"),
    ("Level 1", "Level 2", "Function Description"),
    ("状态", "说明"),
    ("Status", "Description"),
    ("参数", "数值"),
    ("Parameter", "Value"),
    ("项目", "说明"),
    ("Item", "Description"),
)


@dataclass(frozen=True)
class HeaderTableRegion:
    headers: tuple[str, ...]
    vertical_lines: tuple[float, ...]
    clip: fitz.Rect


def _header_row_center(rect: fitz.Rect) -> float:
    return (rect.y0 + rect.y1) / 2.0


def find_header_row(
    page: fitz.Page,
    headers: tuple[str, ...],
    *,
    y_tolerance: float,
) -> list[fitz.Rect] | None:
    """Return header cell rects on one row, left-to-right, or None if not found."""
    hits_by_header: list[list[fitz.Rect]] = []
    for text in headers:
        rects = page.search_for(text)
        if not rects:
            return None
        hits_by_header.append(list(rects))

    anchor_hits = hits_by_header[0]
    for anchor in anchor_hits:
        row = [anchor]
        anchor_y = _header_row_center(anchor)
        failed = False
        for other_hits in hits_by_header[1:]:
            best: fitz.Rect | None = None
            best_delta = float("inf")
            for candidate in other_hits:
                delta = abs(_header_row_center(candidate) - anchor_y)
                if delta <= y_tolerance and delta < best_delta:
                    best_delta = delta
                    best = candidate
            if best is None:
                failed = True
                break
            row.append(best)
        if failed:
            continue
        return sorted(row, key=lambda rect: rect.x0)
    return None


def vertical_lines_from_headers(
    rects: list[fitz.Rect],
    *,
    margin: float,
) -> list[float]:
    """Derive column boundary x-coordinates from header bboxes."""
    if not rects:
        return []
    xs = [rect.x0 for rect in rects]
    x1s = [rect.x1 for rect in rects]
    lines = [xs[0] - margin]
    for index in range(len(rects) - 1):
        lines.append((x1s[index] + xs[index + 1]) / 2.0)
    lines.append(x1s[-1] + margin)
    return lines


def section_boundary_y(page: fitz.Page, after_y: float) -> float | None:
    """Return y0 of the first numbered section heading below after_y."""
    for block in page.get_text("blocks"):
        if len(block) < 5:
            continue
        y0 = float(block[1])
        if y0 <= after_y + 1.0:
            continue
        text = str(block[4]).strip().split("\n", 1)[0]
        if _SECTION_HEADING_RE.match(text):
            return y0
    return None


def clip_from_headers(
    page: fitz.Page,
    header_rects: list[fitz.Rect],
    vertical_lines: list[float],
    *,
    settings: Settings,
) -> fitz.Rect:
    top = min(rect.y0 for rect in header_rects) - settings.pdf_table_header_top_padding
    header_bottom = max(rect.y1 for rect in header_rects)
    bottom = section_boundary_y(page, header_bottom)
    if bottom is None:
        bottom = page.rect.height * settings.pdf_table_header_clip_bottom_ratio
    return fitz.Rect(
        vertical_lines[0],
        max(0.0, top),
        vertical_lines[-1],
        min(page.rect.height, bottom),
    )


def discover_header_table_regions(
    page: fitz.Page,
    *,
    settings: Settings,
) -> list[HeaderTableRegion]:
    """Find all header-aligned table regions on a page."""
    regions: list[HeaderTableRegion] = []
    seen_line_keys: set[tuple[int, ...]] = set()

    for headers in HEADER_SETS:
        header_rects = find_header_row(
            page,
            headers,
            y_tolerance=settings.pdf_table_header_y_tolerance,
        )
        if header_rects is None:
            continue

        vertical_lines = vertical_lines_from_headers(
            header_rects,
            margin=settings.pdf_table_header_margin,
        )
        if len(vertical_lines) < 2:
            continue

        line_key = tuple(int(round(value)) for value in vertical_lines)
        if line_key in seen_line_keys:
            continue
        seen_line_keys.add(line_key)

        clip = clip_from_headers(page, header_rects, vertical_lines, settings=settings)
        if clip.height <= 0 or clip.width <= 0:
            continue

        regions.append(
            HeaderTableRegion(
                headers=headers,
                vertical_lines=tuple(vertical_lines),
                clip=clip,
            )
        )

    regions.sort(key=lambda region: region.clip.y0)
    return regions


def find_tables_for_region(
    page: fitz.Page,
    region: HeaderTableRegion,
    *,
    settings: Settings,
) -> fitz.TableFinder:
    """Run find_tables with header-derived clip and column lines."""
    return page.find_tables(
        clip=region.clip,
        vertical_lines=list(region.vertical_lines),
        horizontal_strategy="text",
        min_words_horizontal=1,
        snap_y_tolerance=settings.pdf_table_header_snap_y_tolerance,
        join_y_tolerance=settings.pdf_table_header_join_y_tolerance,
    )
