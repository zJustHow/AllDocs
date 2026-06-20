"""Shared ingestion data types."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.pdf_embedded_images import ParsedAttachedAsset
from app.services.pdf_toc_types import TocEntry

PAGE_SEPARATOR = "\n\n"

BlockSpan = tuple[int, int, float, float]
PageRow = tuple[
    str | None,
    str,
    int,
    tuple[float, float, float, float] | None,
    list[BlockSpan] | None,
]
LayoutRegion = dict[str, int | list[float]]


@dataclass
class ParsedChunk:
    text: str
    page: int | None
    section: str | None
    chunk_index: int
    layout_bbox: tuple[float, float, float, float] | None = None
    layout_regions: list[LayoutRegion] | None = None
    sort_key: float | None = None
    layout_y1: float | None = None
    attached_assets: list[ParsedAttachedAsset] = field(default_factory=list)


@dataclass
class ParseResult:
    chunks: list[ParsedChunk]
    page_count: int
    ocr_pages: int
    toc_entries: list[TocEntry]
