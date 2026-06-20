"""Document ingestion entry point."""

from __future__ import annotations

from collections.abc import Callable

from app.config import Settings, get_settings
from app.services.caption import CaptionService
from app.services.document_parsers import (
    decode_text_bytes,
    pages_with_bbox,
    parse_docx_pages,
    parse_structured_text_pages,
    strip_html,
)
from app.services.file_types import detect_file_type
from app.services.ingestion_chunking import build_chunks_from_pages
from app.services.ingestion_types import PageRow, ParseResult
from app.services.ocr import OCRService
from app.services.pdf_ingestion import PdfIngestionParser


class IngestionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.ocr = OCRService(self.settings) if self.settings.ocr_enabled else None
        self.caption_service = (
            CaptionService(self.settings) if self.settings.ingest_caption_enabled else None
        )
        self._pdf_parser = PdfIngestionParser(
            self.settings,
            ocr=self.ocr,
            caption_service=self.caption_service,
        )

    def parse_pdf(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        return self._pdf_parser.parse_pdf(file_bytes, on_page_progress=on_page_progress)

    def _parse_text_document(
        self,
        file_bytes: bytes,
        *,
        markdown: bool,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        pages = parse_structured_text_pages(decode_text_bytes(file_bytes), markdown=markdown)
        if not pages:
            raise ValueError("No text extracted from file")
        if on_page_progress is not None:
            on_page_progress(1, 1)
        return ParseResult(
            chunks=build_chunks_from_pages(pages_with_bbox(pages), self.settings),
            page_count=1,
            ocr_pages=0,
            toc_entries=[],
        )

    def _parse_html_document(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        text = strip_html(decode_text_bytes(file_bytes))
        if not text:
            raise ValueError("No text extracted from HTML")
        pages = [(None, text, 1)]
        if on_page_progress is not None:
            on_page_progress(1, 1)
        return ParseResult(
            chunks=build_chunks_from_pages(pages_with_bbox(pages), self.settings),
            page_count=1,
            ocr_pages=0,
            toc_entries=[],
        )

    def _parse_docx_document(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        pages = parse_docx_pages(file_bytes)
        if not pages:
            raise ValueError("No text extracted from Word document")
        if on_page_progress is not None:
            on_page_progress(1, 1)
        return ParseResult(
            chunks=build_chunks_from_pages(pages_with_bbox(pages), self.settings),
            page_count=1,
            ocr_pages=0,
            toc_entries=[],
        )

    def _parse_image_document(
        self,
        file_bytes: bytes,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        if self.ocr is None:
            raise ValueError("OCR is disabled; cannot process image files")
        text = self.ocr.recognize_bytes(file_bytes).strip()
        if not text:
            raise ValueError("No text extracted from image")
        pages: list[PageRow] = [(None, text, 1, None, None)]
        if on_page_progress is not None:
            on_page_progress(1, 1)
        return ParseResult(
            chunks=build_chunks_from_pages(pages, self.settings),
            page_count=1,
            ocr_pages=1,
            toc_entries=[],
        )

    def parse_document(
        self,
        file_bytes: bytes,
        filename: str,
        on_page_progress: Callable[[int, int], None] | None = None,
    ) -> ParseResult:
        file_type = detect_file_type(filename)
        if file_type is None:
            raise ValueError(f"Unsupported file type: {filename}")

        match file_type.extension:
            case ".pdf":
                return self.parse_pdf(file_bytes, on_page_progress=on_page_progress)
            case ".docx":
                return self._parse_docx_document(file_bytes, on_page_progress=on_page_progress)
            case ".txt":
                return self._parse_text_document(
                    file_bytes, markdown=False, on_page_progress=on_page_progress
                )
            case ".md":
                return self._parse_text_document(
                    file_bytes, markdown=True, on_page_progress=on_page_progress
                )
            case ".html" | ".htm":
                return self._parse_html_document(file_bytes, on_page_progress=on_page_progress)
            case ".png" | ".jpg" | ".jpeg" | ".webp":
                return self._parse_image_document(file_bytes, on_page_progress=on_page_progress)
            case _:
                raise ValueError(f"Unsupported file type: {filename}")
