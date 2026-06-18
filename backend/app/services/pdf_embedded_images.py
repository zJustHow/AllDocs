"""Extract embedded bitmap images from PDF pages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import fitz

from app.config import Settings
from app.services.pdf_attach_reading_order import pick_preceding_chunk
from app.services.pdf_geometry import rect_area, rect_intersection_area

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
    figure_number: str | None = None
    caption_text: str | None = None


@dataclass(frozen=True)
class ParsedAttachedAsset:
    asset_type: str
    page: int
    bbox: tuple[float, float, float, float]
    png_bytes: bytes
    width: int
    height: int
    text_summary: str = ""
    figure_caption: str | None = None
    figure_number: str | None = None


def _bbox_key(bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    return tuple(int(round(value)) for value in bbox)


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

                if rect_area(bbox) / page_area > max_coverage:
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
        text_summary=figure.text.strip(),
        figure_caption=figure.caption_text,
        figure_number=figure.figure_number,
    )


def figure_bboxes_on_page(
    figures: list[EmbeddedFigure],
    page_number: int,
) -> list[tuple[float, float, float, float]]:
    return [figure.bbox for figure in figures if figure.page == page_number]


def _figure_overlaps_table_asset(figure: EmbeddedFigure, chunk) -> bool:
    for attached in getattr(chunk, "attached_assets", []) or []:
        if attached.asset_type != "table":
            continue
        overlap = rect_intersection_area(figure.bbox, attached.bbox)
        if overlap <= 0:
            continue
        if overlap / max(rect_area(figure.bbox), 1.0) >= _OVERLAP_SKIP_RATIO:
            return True
    return False


def figure_overlaps_bboxes(
    figure: EmbeddedFigure,
    bboxes: list[tuple[float, float, float, float]],
) -> bool:
    for bbox in bboxes:
        overlap = rect_intersection_area(figure.bbox, bbox)
        if overlap <= 0:
            continue
        if overlap / max(rect_area(figure.bbox), 1.0) >= _OVERLAP_SKIP_RATIO:
            return True
    return False


def attach_figures_to_chunks(
    figures: list[EmbeddedFigure],
    chunks: list,
) -> list[EmbeddedFigure]:
    """Attach figures to preceding text chunks by reading order; return orphans."""
    if not figures:
        return []

    orphans: list[EmbeddedFigure] = []
    for figure in sorted(figures, key=lambda item: (item.page, item.sort_key)):
        page_chunks = [
            chunk
            for chunk in chunks
            if getattr(chunk, "page", None) == figure.page
        ]
        if any(_figure_overlaps_table_asset(figure, chunk) for chunk in page_chunks):
            continue

        target = pick_preceding_chunk(
            chunks,
            page=figure.page,
            section=figure.section,
            asset_bbox=figure.bbox,
            asset_sort_key=figure.sort_key,
        )
        if target is None:
            orphans.append(figure)
            continue
        target.attached_assets.append(_figure_to_attached_asset(figure))

    return orphans
