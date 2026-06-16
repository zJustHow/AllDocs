"""Extract embedded bitmap images from PDF pages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import fitz

from app.config import Settings

_ATTACHABLE_CHUNK_TYPES = frozenset({"text", "procedure", "warning"})
_OVERLAP_SKIP_RATIO = 0.35


@dataclass(frozen=True)
class EmbeddedFigure:
    page: int
    section: str | None
    bbox: tuple[float, float, float, float]
    sort_key: float
    text: str
    png_bytes: bytes
    width: int
    height: int


@dataclass(frozen=True)
class ParsedAttachedAsset:
    asset_type: str
    page: int
    bbox: tuple[float, float, float, float]
    png_bytes: bytes
    width: int
    height: int


def _bbox_key(bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    return tuple(int(round(value)) for value in bbox)


def _rect_area(bbox: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _xref_to_png(doc: fitz.Document, xref: int) -> tuple[bytes, int, int] | None:
    pix: fitz.Pixmap | None = None
    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.n - pix.alpha >= 4:
            converted = fitz.Pixmap(fitz.csRGB, pix)
            pix = None
            pix = converted
        return pix.tobytes("png"), pix.width, pix.height
    except Exception:
        return None
    finally:
        if pix is not None:
            pix = None


def extract_pdf_embedded_figures(
    doc: fitz.Document,
    *,
    settings: Settings,
    section_resolver: Callable[[int, float | None], str | None],
    should_skip_page: Callable[[int], bool] | None = None,
) -> list[EmbeddedFigure]:
    if not settings.pdf_extract_embedded_images:
        return []

    min_width = settings.pdf_embedded_image_min_width
    min_height = settings.pdf_embedded_image_min_height
    max_coverage = settings.pdf_embedded_image_max_page_coverage
    max_per_page = settings.pdf_embedded_image_max_per_page

    figures: list[EmbeddedFigure] = []
    seen_placements: set[tuple[int, int, tuple[int, int, int, int]]] = set()
    png_cache: dict[int, tuple[bytes, int, int]] = {}

    for page_index in range(doc.page_count):
        page_number = page_index + 1
        if should_skip_page and should_skip_page(page_number):
            continue

        page = doc[page_index]
        page_area = float(page.rect.width * page.rect.height)
        if page_area <= 0:
            continue

        page_count = 0
        for image in page.get_images(full=True):
            if page_count >= max_per_page:
                break

            xref = int(image[0])
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue
            if not rects:
                continue

            if xref not in png_cache:
                converted = _xref_to_png(doc, xref)
                if converted is None:
                    png_cache[xref] = (b"", 0, 0)
                else:
                    png_cache[xref] = converted

            png_bytes, width, height = png_cache[xref]
            if not png_bytes:
                continue
            if width < min_width or height < min_height:
                continue

            for rect in rects:
                if page_count >= max_per_page:
                    break

                bbox = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
                key = (page_number, xref, _bbox_key(bbox))
                if key in seen_placements:
                    continue
                seen_placements.add(key)

                if _rect_area(bbox) / page_area > max_coverage:
                    continue

                display_width = max(1.0, bbox[2] - bbox[0])
                display_height = max(1.0, bbox[3] - bbox[1])
                if display_width < min_width or display_height < min_height:
                    continue

                mid_y = (bbox[1] + bbox[3]) / 2
                text = page.get_text("text", clip=rect).strip()
                figures.append(
                    EmbeddedFigure(
                        page=page_number,
                        section=section_resolver(page_number, mid_y),
                        bbox=bbox,
                        sort_key=float(rect.y0),
                        text=text,
                        png_bytes=png_bytes,
                        width=width,
                        height=height,
                    )
                )
                page_count += 1

    return figures


def _figure_to_attached_asset(figure: EmbeddedFigure) -> ParsedAttachedAsset:
    return ParsedAttachedAsset(
        asset_type="figure",
        page=figure.page,
        bbox=figure.bbox,
        png_bytes=figure.png_bytes,
        width=figure.width,
        height=figure.height,
    )


def _rect_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)


def _figure_overlaps_table(figure: EmbeddedFigure, chunk) -> bool:
    if getattr(chunk, "chunk_type", "") != "table":
        return False
    chunk_bbox = getattr(chunk, "asset_bbox", None)
    if not chunk_bbox:
        return False
    overlap = _rect_intersection_area(figure.bbox, chunk_bbox)
    if overlap <= 0:
        return False
    return overlap / max(_rect_area(figure.bbox), 1.0) >= _OVERLAP_SKIP_RATIO


def _chunk_layout_bbox(chunk) -> tuple[float, float, float, float] | None:
    bbox = getattr(chunk, "asset_bbox", None)
    if bbox and len(bbox) == 4:
        return tuple(float(value) for value in bbox)
    return None


def _vertical_distance(
    figure_y: float,
    bbox: tuple[float, float, float, float],
) -> float:
    y0, y1 = bbox[1], bbox[3]
    if y0 <= figure_y <= y1:
        return 0.0
    return min(abs(figure_y - y0), abs(figure_y - y1))


def _is_attach_candidate(chunk) -> bool:
    page = getattr(chunk, "page", None)
    chunk_type = getattr(chunk, "chunk_type", "text")
    if page is None or chunk_type not in _ATTACHABLE_CHUNK_TYPES:
        return False
    if getattr(chunk, "asset_png", None):
        return False
    return True


def _pick_nearest_chunk(figure: EmbeddedFigure, candidates: list) -> object | None:
    figure_y = (figure.bbox[1] + figure.bbox[3]) / 2
    pool = [chunk for chunk in candidates if _is_attach_candidate(chunk)]
    if not pool:
        return None

    if figure.section:
        section_pool = [chunk for chunk in pool if chunk.section == figure.section]
        if section_pool:
            pool = section_pool

    bbox_pool = [chunk for chunk in pool if _chunk_layout_bbox(chunk)]
    if bbox_pool:
        pool = bbox_pool

    def rank(chunk: object) -> tuple[float, int, int]:
        bbox = _chunk_layout_bbox(chunk)
        if bbox:
            distance = _vertical_distance(figure_y, bbox)
            prefer_above = 0 if bbox[3] <= figure_y else 1
            return (distance, prefer_above, int(getattr(chunk, "chunk_index", 0)))
        slot = int(getattr(chunk, "chunk_index", 0))
        return (float("inf"), 1, slot)

    return min(pool, key=rank)


def attach_figures_to_chunks(
    figures: list[EmbeddedFigure],
    chunks: list,
) -> list[EmbeddedFigure]:
    """Attach figures to nearby text/procedure/warning chunks; return orphans."""
    if not figures:
        return []

    table_chunks = [
        chunk
        for chunk in chunks
        if getattr(chunk, "chunk_type", "") == "table"
    ]

    by_page: dict[int, list] = {}
    for chunk in chunks:
        page = getattr(chunk, "page", None)
        if page is None:
            continue
        by_page.setdefault(int(page), []).append(chunk)

    figures_by_page: dict[int, list[EmbeddedFigure]] = {}
    for figure in figures:
        if any(_figure_overlaps_table(figure, table_chunk) for table_chunk in table_chunks):
            continue
        figures_by_page.setdefault(figure.page, []).append(figure)
    for page_figures in figures_by_page.values():
        page_figures.sort(key=lambda item: item.sort_key)

    orphans: list[EmbeddedFigure] = []
    for page, page_figures in figures_by_page.items():
        candidates = by_page.get(page, [])
        for figure in page_figures:
            target = _pick_nearest_chunk(figure, candidates)
            if target is None:
                orphans.append(figure)
                continue
            target.attached_assets.append(_figure_to_attached_asset(figure))

    return orphans


def attach_figures_to_text_chunks(
    figures: list[EmbeddedFigure],
    chunks: list,
) -> list[EmbeddedFigure]:
    return attach_figures_to_chunks(figures, chunks)
