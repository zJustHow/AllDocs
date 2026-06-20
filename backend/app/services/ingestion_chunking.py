"""Build ParsedChunk rows from extracted page text."""

from __future__ import annotations

import re

from app.config import Settings
from app.services.ingestion_types import (
    PAGE_SEPARATOR,
    BlockSpan,
    LayoutRegion,
    PageRow,
    ParsedChunk,
)
from app.services.pdf_embedded_images import EmbeddedFigure, ParsedAttachedAsset, _figure_to_attached_asset
from app.services.pdf_layout_regions import layout_region
from app.services.pdf_tables import EmbeddedTable, _table_to_attached_asset


def split_text_with_offsets(
    text: str, chunk_size: int, overlap: int
) -> list[tuple[int, str]]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [(0, text)]

    chunks: list[tuple[int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            split_at = text.rfind("\n", start + chunk_size // 2, end)
            if split_at == -1:
                split_at = text.rfind("。", start + chunk_size // 2, end)
            if split_at == -1:
                split_at = text.rfind(". ", start + chunk_size // 2, end)
            if split_at != -1:
                end = split_at + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append((start, piece))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def block_spans_from_joined_blocks(
    texts: list[str],
    block_bounds: list[tuple[float, float]],
) -> list[BlockSpan]:
    spans: list[BlockSpan] = []
    offset = 0
    for index, (text, (y0, y1)) in enumerate(zip(texts, block_bounds, strict=True)):
        if index > 0:
            offset += 1
        start = offset
        offset += len(text)
        spans.append((start, offset, y0, y1))
    return spans


def y_bounds_for_range(
    block_spans: list[BlockSpan],
    start: int,
    end: int,
) -> tuple[float, float] | None:
    y0_values: list[float] = []
    y1_values: list[float] = []
    for span_start, span_end, y0, y1 in block_spans:
        if span_end <= start or span_start >= end:
            continue
        y0_values.append(y0)
        y1_values.append(y1)
    if not y0_values:
        return None
    return (min(y0_values), max(y1_values))


def layout_y_bounds(
    layout_bbox: tuple[float, float, float, float] | None,
) -> tuple[float | None, float | None]:
    if layout_bbox is None:
        return None, None
    return float(layout_bbox[1]), float(layout_bbox[3])


def merge_bboxes(
    bboxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    if not bboxes:
        return None
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def group_contiguous_sections(
    pages: list[PageRow],
) -> list[tuple[str | None, list[tuple[int, str, tuple[float, float, float, float] | None, list[BlockSpan] | None]]]]:
    if not pages:
        return []

    groups: list[
        tuple[str | None, list[tuple[int, str, tuple[float, float, float, float] | None, list[BlockSpan] | None]]]
    ] = []
    current_section = pages[0][0]
    current_pages: list[tuple[int, str, tuple[float, float, float, float] | None, list[BlockSpan] | None]] = [
        (pages[0][2], pages[0][1], pages[0][3], pages[0][4])
    ]

    for section, text, page, bbox, block_spans in pages[1:]:
        if section != current_section:
            groups.append((current_section, current_pages))
            current_section = section
            current_pages = []
        current_pages.append((page, text, bbox, block_spans))
    groups.append((current_section, current_pages))
    return groups


def concat_pages(
    pages: list[tuple[int, str, tuple[float, float, float, float] | None, list[BlockSpan] | None]],
    separator: str = PAGE_SEPARATOR,
) -> tuple[str, list[tuple[int, int, tuple[float, float, float, float] | None]], list[BlockSpan]]:
    spans: list[tuple[int, int, tuple[float, float, float, float] | None]] = []
    block_spans: list[BlockSpan] = []
    parts: list[str] = []
    offset = 0
    for index, (page, text, bbox, page_block_spans) in enumerate(pages):
        if index > 0:
            offset += len(separator)
        spans.append((page, offset, bbox))
        if page_block_spans:
            for span_start, span_end, y0, y1 in page_block_spans:
                block_spans.append((offset + span_start, offset + span_end, y0, y1))
        parts.append(text)
        offset += len(text)
    return separator.join(parts), spans, block_spans


def page_for_offset(spans: list[tuple[int, int, tuple[float, float, float, float] | None]], offset: int) -> int:
    page = spans[0][0]
    for span_page, start, _bbox in spans:
        if start <= offset:
            page = span_page
        else:
            break
    return page


def bbox_for_offset(
    spans: list[tuple[int, int, tuple[float, float, float, float] | None]],
    offset: int,
) -> tuple[float, float, float, float] | None:
    bbox: tuple[float, float, float, float] | None = None
    for _page, start, span_bbox in spans:
        if start <= offset:
            bbox = span_bbox
        else:
            break
    return bbox


def regions_for_range(
    page_spans: list[tuple[int, int, tuple[float, float, float, float] | None]],
    block_spans: list[BlockSpan],
    start: int,
    end: int,
    total_len: int,
    separator_len: int = len(PAGE_SEPARATOR),
) -> list[LayoutRegion]:
    if not page_spans or start >= end:
        return []

    regions: list[LayoutRegion] = []
    for index, (page, page_start, page_bbox) in enumerate(page_spans):
        if page_bbox is None:
            continue
        if index + 1 < len(page_spans):
            page_end = page_spans[index + 1][1] - separator_len
        else:
            page_end = total_len

        overlap_start = max(start, page_start)
        overlap_end = min(end, page_end)
        if overlap_start >= overlap_end:
            continue

        y0_values: list[float] = []
        y1_values: list[float] = []
        for span_start, span_end, y0, y1 in block_spans:
            if span_end <= overlap_start or span_start >= overlap_end:
                continue
            if span_end <= page_start or span_start >= page_end:
                continue
            y0_values.append(y0)
            y1_values.append(y1)

        if y0_values:
            region_bbox = (page_bbox[0], min(y0_values), page_bbox[2], max(y1_values))
        else:
            region_bbox = page_bbox

        regions.append(layout_region(page, region_bbox))

    return regions


def merge_pdf_layout_chunks(
    inline_chunks: list[tuple[int, float, ParsedChunk]],
    page_chunks: list[ParsedChunk],
) -> list[ParsedChunk]:
    ordered: list[tuple[int, float, int, ParsedChunk]] = []

    for page, sort_key, chunk in inline_chunks:
        ordered.append((page, sort_key, 0, chunk))

    for chunk in page_chunks:
        ordered.append((chunk.page or 0, float("inf"), chunk.chunk_index + 1, chunk))

    ordered.sort(key=lambda item: (item[0], item[1], item[2]))
    merged: list[ParsedChunk] = []
    for index, (_, _, _, chunk) in enumerate(ordered):
        chunk.chunk_index = index
        merged.append(chunk)
    return merged


def orphan_figure_chunk(figure: EmbeddedFigure) -> ParsedChunk:
    return ParsedChunk(
        text="",
        page=figure.page,
        section=figure.section,
        chunk_index=0,
        layout_bbox=figure.bbox,
        layout_regions=[layout_region(figure.page, figure.bbox)],
        sort_key=float(figure.bbox[1]),
        layout_y1=float(figure.bbox[3]),
        attached_assets=[_figure_to_attached_asset(figure)],
    )


def orphan_table_chunk(table: EmbeddedTable) -> ParsedChunk:
    regions = (
        list(table.layout_regions)
        if table.layout_regions
        else [layout_region(table.page, table.bbox)]
    )
    return ParsedChunk(
        text="",
        page=table.page,
        section=table.section,
        chunk_index=0,
        layout_bbox=table.bbox,
        layout_regions=regions,
        sort_key=float(table.bbox[1]),
        layout_y1=float(table.bbox[3]),
        attached_assets=[_table_to_attached_asset(table)],
    )


def build_chunks_from_pages(
    pages: list[PageRow],
    settings: Settings,
) -> list[ParsedChunk]:
    parsed_chunks: list[ParsedChunk] = []
    chunk_index = 0
    for section, page_group in group_contiguous_sections(pages):
        section_text, page_spans, block_spans = concat_pages(page_group)
        for offset, piece in split_text_with_offsets(
            section_text,
            settings.rag_chunk_size,
            settings.rag_chunk_overlap,
        ):
            chunk_end = offset + len(piece)
            layout_regions = regions_for_range(
                page_spans,
                block_spans,
                offset,
                chunk_end,
                len(section_text),
            )
            layout_bbox = bbox_for_offset(page_spans, offset)
            if layout_regions:
                first_bbox = layout_regions[0]["bbox"]
                if isinstance(first_bbox, list) and len(first_bbox) == 4:
                    layout_bbox = tuple(float(value) for value in first_bbox)
            y_bounds = y_bounds_for_range(block_spans, offset, chunk_end)
            if y_bounds is not None:
                sort_key, layout_y1 = y_bounds
            else:
                sort_key, layout_y1 = layout_y_bounds(layout_bbox)
            parsed_chunks.append(
                ParsedChunk(
                    text=piece,
                    page=page_for_offset(page_spans, offset),
                    section=section,
                    chunk_index=chunk_index,
                    layout_bbox=layout_bbox,
                    layout_regions=layout_regions or None,
                    sort_key=sort_key,
                    layout_y1=layout_y1,
                )
            )
            chunk_index += 1
    return parsed_chunks
