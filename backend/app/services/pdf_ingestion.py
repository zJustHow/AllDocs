"""PDF document ingestion: per-page extraction and chunk assembly."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import fitz

from app.config import Settings
from app.services.caption import CaptionService
from app.services.ingestion_chunking import (
    build_chunks_from_pages,
    merge_pdf_layout_chunks,
    orphan_figure_chunk,
    orphan_table_chunk,
)
from app.services.ingestion_types import PageRow, ParseResult, ParsedChunk
from app.services.ocr import OCRService
from app.services.pdf_captions import apply_page_caption_matches, extract_page_captions
from app.services.pdf_embedded_images import (
    EmbeddedFigure,
    attach_figures_to_chunks,
    extract_figures_from_page,
    figure_bboxes_on_page,
    figure_overlaps_bboxes,
)
from app.services.pdf_header_footer import HeaderFooterFilter, build_header_footer_filter
from app.services.pdf_page_text import (
    extract_native_page_text,
    is_toc_text,
    page_content_bbox,
    page_needs_ocr,
    page_row_from_blocks,
    segment_page_by_anchors,
)
from app.services.pdf_refs import attach_by_explicit_refs
from app.services.pdf_table_merge import merge_cross_page_tables
from app.services.pdf_tables import (
    EmbeddedTable,
    attach_tables_to_chunks,
    extract_tables_from_page,
    filter_page_blocks,
    filter_page_text,
    table_bboxes_on_page,
)
from app.services.pdf_toc import (
    TocAnchor,
    TocEntry,
    parse_pdf_toc,
    section_at_position,
    section_for_page,
    should_skip_front_matter,
)
from app.services.pdf_vlm_route import route_figures_via_vlm

logger = logging.getLogger(__name__)


@dataclass
class PdfPageParseResult:
    page_number: int
    pages: list[PageRow]
    tables: list[EmbeddedTable]
    figures: list[EmbeddedFigure]
    ocr_pages: int
    tables_available: bool


class PdfIngestionParser:
    def __init__(
        self,
        settings: Settings,
        *,
        ocr: OCRService | None,
        caption_service: CaptionService | None,
    ) -> None:
        self.settings = settings
        self.ocr = ocr
        self.caption_service = caption_service

    def _render_page_for_ocr(self, page: fitz.Page) -> tuple[bytes, float]:
        scale = self.settings.ocr_render_scale
        matrix = fitz.Matrix(scale, scale)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        return pixmap.tobytes("png"), float(page.rect.height) * scale

    def _recognize_rendered_page(
        self,
        png_bytes: bytes,
        page_height: float,
        hf: HeaderFooterFilter | None,
    ) -> str:
        if self.ocr is None:
            return ""
        return self.ocr.recognize_bytes(
            png_bytes,
            page_height=page_height,
            hf=hf,
        )

    def _extract_page_text_with_ocr(
        self,
        page: fitz.Page,
        *,
        hf: HeaderFooterFilter | None,
        exclude_bboxes: list[tuple[float, float, float, float]],
    ) -> tuple[str, bool]:
        native_text = extract_native_page_text(page, hf=hf)

        if exclude_bboxes and not self.settings.ocr_force:
            return filter_page_text(page, exclude_bboxes, hf=hf), False

        used_ocr = False
        if page_needs_ocr(native_text, self.settings) and self.ocr is not None:
            png_bytes, page_height = self._render_page_for_ocr(page)
            ocr_text = self._recognize_rendered_page(png_bytes, page_height, hf)
            if len(ocr_text.strip()) > len(native_text.strip()):
                native_text = ocr_text
                used_ocr = True

        page_text = native_text
        if exclude_bboxes and page_text.strip():
            page_text = filter_page_text(page, exclude_bboxes, hf=hf) or page_text
        return page_text, used_ocr

    def _append_page_text_rows(
        self,
        pages: list[PageRow],
        *,
        page: fitz.Page,
        page_number: int,
        page_text: str,
        used_ocr: bool,
        exclude_bboxes: list[tuple[float, float, float, float]],
        toc_anchors: list[TocAnchor],
        toc_entries: list[TocEntry],
        use_y_split: bool,
        hf_filter: HeaderFooterFilter | None,
    ) -> None:
        if not page_text.strip() and not exclude_bboxes:
            return
        if page_text.strip() and is_toc_text(page_text):
            return

        fallback_section = section_for_page(toc_entries, page_number)
        if use_y_split and not used_ocr and page_text.strip():
            blocks = filter_page_blocks(page, exclude_bboxes, hf=hf_filter)
            if blocks:
                for section, segment_text, segment_bbox, block_spans in segment_page_by_anchors(
                    toc_anchors,
                    page_number,
                    blocks,
                    fallback_section,
                ):
                    if segment_text.strip():
                        pages.append(
                            (
                                section,
                                segment_text.strip(),
                                page_number,
                                segment_bbox,
                                block_spans,
                            )
                        )
            elif page_text.strip():
                pages.append(
                    (
                        fallback_section,
                        page_text.strip(),
                        page_number,
                        page_content_bbox(page, exclude_bboxes, hf=hf_filter),
                        None,
                    )
                )
        elif page_text.strip():
            blocks = filter_page_blocks(page, exclude_bboxes, hf=hf_filter)
            row = page_row_from_blocks(
                fallback_section,
                page_number,
                blocks,
                page_content_bbox(page, exclude_bboxes, hf=hf_filter),
            )
            if row is not None:
                pages.append(row)

    def _section_resolver(
        self,
        toc_entries: list[TocEntry],
        toc_anchors: list[TocAnchor],
        use_y_split: bool,
    ) -> Callable[[int, float | None], str | None]:
        def section_resolver(page_number: int, y: float | None = None) -> str | None:
            if y is not None and use_y_split:
                resolved = section_at_position(toc_anchors, page_number, y)
                if resolved:
                    return resolved
            return section_for_page(toc_entries, page_number)

        return section_resolver

    def _parse_pdf_page(
        self,
        *,
        doc: fitz.Document,
        page_index: int,
        toc_entries: list[TocEntry],
        toc_anchors: list[TocAnchor],
        use_y_split: bool,
        hf_filter: HeaderFooterFilter,
        tables_available: bool,
        png_cache: dict[int, tuple[bytes, int, int]],
        seen_placements: set[tuple[int, int, tuple[int, int, int, int]]],
    ) -> PdfPageParseResult:
        page_number = page_index + 1
        page = doc[page_index]
        section_resolver = self._section_resolver(toc_entries, toc_anchors, use_y_split)
        page_rows: list[PageRow] = []

        page_tables: list[EmbeddedTable] = []
        if tables_available:
            try:
                page_tables = extract_tables_from_page(
                    page,
                    page_number,
                    settings=self.settings,
                    section_resolver=section_resolver,
                )
            except AttributeError:
                logger.warning(
                    "PyMuPDF find_tables is unavailable; table extraction disabled"
                )
                tables_available = False

        page_figures = extract_figures_from_page(
            page,
            page_number,
            doc,
            settings=self.settings,
            section_resolver=section_resolver,
            png_cache=png_cache,
            seen_placements=seen_placements,
        )
        table_bboxes = table_bboxes_on_page(page_tables, page_number)
        page_figures = [
            figure
            for figure in page_figures
            if not figure_overlaps_bboxes(figure, table_bboxes)
        ]

        page_captions = extract_page_captions(page, page_number)
        page_figures, page_tables = apply_page_caption_matches(
            page_captions,
            page_figures,
            page_tables,
        )

        page_figures, promoted = route_figures_via_vlm(
            page_figures,
            settings=self.settings,
            caption_service=self.caption_service,
        )
        page_tables = [*page_tables, *promoted]

        exclude_bboxes = (
            table_bboxes_on_page(page_tables, page_number)
            + figure_bboxes_on_page(page_figures, page_number)
        )

        page_text, used_ocr = self._extract_page_text_with_ocr(
            page,
            hf=hf_filter,
            exclude_bboxes=exclude_bboxes,
        )

        self._append_page_text_rows(
            page_rows,
            page=page,
            page_number=page_number,
            page_text=page_text,
            used_ocr=used_ocr,
            exclude_bboxes=exclude_bboxes,
            toc_anchors=toc_anchors,
            toc_entries=toc_entries,
            use_y_split=use_y_split,
            hf_filter=hf_filter,
        )

        return PdfPageParseResult(
            page_number=page_number,
            pages=page_rows,
            tables=page_tables,
            figures=page_figures,
            ocr_pages=1 if used_ocr else 0,
            tables_available=tables_available,
        )

    def parse_pdf(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = doc.page_count
        toc_entries, toc_anchors = parse_pdf_toc(doc)
        use_y_split = any(anchor.has_y for anchor in toc_anchors)
        skip_front_matter = lambda page_number: should_skip_front_matter(
            page_number, toc_entries
        )
        hf_filter = build_header_footer_filter(
            doc,
            self.settings,
            should_skip_page=skip_front_matter,
        )

        pages: list[PageRow] = []
        ocr_pages = 0
        extracted_tables: list[EmbeddedTable] = []
        embedded_figures: list[EmbeddedFigure] = []
        png_cache: dict[int, tuple[bytes, int, int]] = {}
        seen_placements: set[tuple[int, int, tuple[int, int, int, int]]] = set()
        tables_available = True
        page_indices = [
            page_index
            for page_index in range(page_count)
            if not should_skip_front_matter(page_index + 1, toc_entries)
        ]

        for page_index in page_indices:
            result = self._parse_pdf_page(
                doc=doc,
                page_index=page_index,
                toc_entries=toc_entries,
                toc_anchors=toc_anchors,
                use_y_split=use_y_split,
                hf_filter=hf_filter,
                tables_available=tables_available,
                png_cache=png_cache,
                seen_placements=seen_placements,
            )
            pages.extend(result.pages)
            extracted_tables.extend(result.tables)
            embedded_figures.extend(result.figures)
            ocr_pages += result.ocr_pages
            tables_available = result.tables_available
            if on_page_progress is not None:
                on_page_progress(result.page_number, page_count)

        if extracted_tables:
            page_heights = {
                page_index + 1: float(doc[page_index].rect.height)
                for page_index in range(page_count)
            }
            extracted_tables = merge_cross_page_tables(
                extracted_tables,
                page_heights=page_heights,
                settings=self.settings,
            )

        if not pages and not embedded_figures and not extracted_tables:
            doc.close()
            raise ValueError("No text extracted from PDF")

        page_chunks = build_chunks_from_pages(pages, self.settings) if pages else []

        remaining_figures, remaining_tables = attach_by_explicit_refs(
            page_chunks,
            embedded_figures,
            extracted_tables,
        )

        orphan_tables = attach_tables_to_chunks(remaining_tables, page_chunks)
        orphan_figures = attach_figures_to_chunks(remaining_figures, page_chunks)

        inline_chunks: list[tuple[int, float, ParsedChunk]] = []
        for table in orphan_tables:
            inline_chunks.append((table.page, table.sort_key, orphan_table_chunk(table)))
        for figure in orphan_figures:
            inline_chunks.append((figure.page, figure.sort_key, orphan_figure_chunk(figure)))

        parsed_chunks = (
            merge_pdf_layout_chunks(inline_chunks, page_chunks)
            if inline_chunks
            else page_chunks
        )

        doc.close()
        return ParseResult(
            chunks=parsed_chunks,
            page_count=page_count,
            ocr_pages=ocr_pages,
            toc_entries=toc_entries,
        )
