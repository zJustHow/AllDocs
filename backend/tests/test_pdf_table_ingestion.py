"""Integration tests for PDF table extraction through ingestion."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import fitz

from app.config import Settings
from app.services.ingestion import (
    IngestionService,
    _merge_pdf_layout_chunks,
    _orphan_table_chunk,
)
from app.services.pdf_captions import (
    LayoutCaption,
    apply_page_caption_matches,
    extract_page_captions,
)
from app.services.pdf_embedded_images import EmbeddedFigure
from app.services.pdf_refs import attach_by_explicit_refs
from app.services.pdf_table_header_detect import discover_header_table_regions
from app.services.pdf_tables import EmbeddedTable, extract_tables_from_page


def _ingestion_settings(**overrides: object) -> Settings:
    base = {
        "ocr_enabled": False,
        "ingest_caption_enabled": False,
        "pdf_extract_tables": True,
        "pdf_table_header_detect_enabled": True,
        "pdf_parallel_workers": 1,
        "rag_chunk_size": 500,
    }
    base.update(overrides)
    return Settings(**base)


def _draw_grid_table(
    page: fitz.Page,
    *,
    top: float,
    left: float = 50.0,
    header_a: str = "Status",
    header_b: str = "Description",
    row_a: str = "Idle",
    row_b: str = "Ready",
) -> tuple[float, float, float, float]:
    cols = [left, left + 150.0, left + 350.0]
    rows = [top, top + 30.0, top + 60.0, top + 90.0]
    for x in cols:
        page.draw_line((x, rows[0]), (x, rows[-1]))
    for y in rows:
        page.draw_line((cols[0], y), (cols[-1], y))
    page.insert_text((cols[0] + 10.0, rows[0] + 5.0), header_a, fontsize=10)
    page.insert_text((cols[1] + 10.0, rows[0] + 5.0), header_b, fontsize=10)
    page.insert_text((cols[0] + 10.0, rows[1] + 5.0), row_a, fontsize=10)
    page.insert_text((cols[1] + 10.0, rows[1] + 5.0), row_b, fontsize=10)
    return (cols[0], rows[0], cols[-1], rows[-1])


def _single_page_table_pdf(*, with_intro: bool = True, caption_below: bool = False) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    if with_intro:
        page.insert_text(
            (50.0, 80.0),
            "Before starting, review the status table.",
            fontsize=12,
        )
    _draw_grid_table(page, top=200.0)
    if caption_below:
        page.insert_text((50.0, 320.0), "Table 2-1 Status codes", fontsize=10)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _cross_page_table_pdf() -> bytes:
    doc = fitz.open()
    page1 = doc.new_page(width=600, height=800)
    page1.insert_text((50.0, 80.0), "Page one intro.", fontsize=12)
    _draw_grid_table(
        page1,
        top=620.0,
        header_a="Model",
        header_b="Voltage",
        row_a="A1",
        row_b="220V",
    )

    page2 = doc.new_page(width=600, height=800)
    _draw_grid_table(
        page2,
        top=40.0,
        header_a="Model",
        header_b="Voltage",
        row_a="A2",
        row_b="110V",
    )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _header_guided_doc() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((10.0, 100.0), "Status", fontsize=12)
    page.insert_text((200.0, 100.0), "Description", fontsize=12)
    page.insert_text((10.0, 130.0), "Idle", fontsize=10)
    page.insert_text((200.0, 130.0), "Ready state", fontsize=10)
    page.insert_text((10.0, 500.0), "4.6 Next section", fontsize=12)
    return doc


class TestRealPdfTableExtraction:
    def test_extract_tables_from_drawn_grid(self) -> None:
        doc = fitz.open(stream=_single_page_table_pdf(with_intro=False), filetype="pdf")
        try:
            page = doc[0]
            settings = _ingestion_settings(pdf_table_header_detect_enabled=False)
            tables = extract_tables_from_page(
                page,
                1,
                settings=settings,
                section_resolver=lambda _page, _y: "S1",
            )
        finally:
            doc.close()

        assert len(tables) == 1
        assert "Status" in tables[0].summary
        assert "Description" in tables[0].summary
        assert "Idle" in tables[0].summary
        assert tables[0].png_bytes.startswith(b"\x89PNG")

    def test_header_guided_discovery_on_searchable_pdf_text(self) -> None:
        doc = _header_guided_doc()
        try:
            regions = discover_header_table_regions(doc[0], settings=_ingestion_settings())
        finally:
            doc.close()

        assert len(regions) == 1
        assert regions[0].headers == ("Status", "Description")
        assert len(regions[0].vertical_lines) >= 2
        assert regions[0].clip.y1 > regions[0].clip.y0

    def test_chinese_headers_are_searchable_with_cjk_font(self) -> None:
        doc = fitz.open()
        try:
            page = doc.new_page(width=600, height=800)
            page.insert_text((10.0, 100.0), "状态", fontname="china-s", fontsize=12)
            page.insert_text((120.0, 100.0), "说明", fontname="china-s", fontsize=12)
            hits = page.search_for("状态") + page.search_for("说明")
            assert len(hits) == 2

            regions = discover_header_table_regions(page, settings=_ingestion_settings())
            assert len(regions) == 1
            assert regions[0].headers == ("状态", "说明")
        finally:
            doc.close()


class TestPdfCaptionTablePairing:
    def test_apply_page_caption_matches_pairs_nearby_table(self) -> None:
        doc = fitz.open(stream=_single_page_table_pdf(caption_below=True), filetype="pdf")
        try:
            page = doc[0]
            settings = _ingestion_settings()
            tables = extract_tables_from_page(
                page,
                1,
                settings=settings,
                section_resolver=lambda _page, _y: "S1",
            )
            captions = extract_page_captions(page, 1)

            _, matched_tables = apply_page_caption_matches(captions, [], tables)

            assert len(matched_tables) == 1
            assert matched_tables[0].figure_number == "2-1"
            assert matched_tables[0].caption_text == "Table 2-1 Status codes"
        finally:
            doc.close()

    def test_apply_page_caption_skips_non_matching_kind(self) -> None:
        table = EmbeddedTable(
            page=1,
            section="S1",
            bbox=(50.0, 200.0, 400.0, 290.0),
            sort_key=200.0,
            summary="| A | B |",
            png_bytes=b"png",
            width=10,
            height=10,
        )
        caption = LayoutCaption(
            kind="figure",
            figure_number="4-7",
            description="Illustration",
            full_text="Figure 4-7 Illustration",
            bbox=(50.0, 300.0, 400.0, 320.0),
            page=1,
        )

        figures, tables = apply_page_caption_matches([caption], [], [table])

        assert tables[0].figure_number is None
        assert figures == []


class TestIngestionTableHelpers:
    def test_orphan_table_chunk_wraps_asset_and_regions(self) -> None:
        table = EmbeddedTable(
            page=2,
            section="Servo",
            bbox=(10.0, 160.0, 500.0, 320.0),
            sort_key=160.0,
            summary="| A | B |",
            png_bytes=b"png",
            width=100,
            height=80,
            layout_regions=({"page": 2, "bbox": [10.0, 160.0, 500.0, 320.0]},),
        )

        chunk = _orphan_table_chunk(table)

        assert chunk.text == ""
        assert chunk.page == 2
        assert chunk.section == "Servo"
        assert len(chunk.attached_assets) == 1
        assert chunk.attached_assets[0].asset_type == "table"
        assert chunk.attached_assets[0].text_summary == "| A | B |"
        assert chunk.layout_regions == [{"page": 2, "bbox": [10.0, 160.0, 500.0, 320.0]}]

    def test_merge_pdf_layout_chunks_interleaves_orphan_tables(self) -> None:
        text_chunk = SimpleNamespace(
            page=1,
            chunk_index=0,
            text="正文",
            section="S1",
            sort_key=100.0,
            layout_y1=180.0,
            layout_bbox=(0.0, 100.0, 500.0, 180.0),
            attached_assets=[],
            layout_regions=[],
        )
        table = EmbeddedTable(
            page=1,
            section="S1",
            bbox=(10.0, 200.0, 500.0, 400.0),
            sort_key=200.0,
            summary="| A | B |",
            png_bytes=b"png",
            width=100,
            height=80,
        )
        inline = [(1, 200.0, _orphan_table_chunk(table))]

        merged = _merge_pdf_layout_chunks(inline, [text_chunk])

        assert len(merged) == 2
        assert merged[0].text == ""
        assert merged[0].attached_assets
        assert merged[1].text == "正文"
        assert merged[0].chunk_index == 0
        assert merged[1].chunk_index == 1


class TestIngestionServiceParsePdf:
    def test_parse_pdf_attaches_table_to_preceding_text_chunk(self) -> None:
        service = IngestionService(settings=_ingestion_settings())
        result = service.parse_pdf(_single_page_table_pdf())

        table_chunks = [
            chunk
            for chunk in result.chunks
            if any(asset.asset_type == "table" for asset in chunk.attached_assets)
        ]
        assert len(table_chunks) == 1
        chunk = table_chunks[0]
        assert "status table" in chunk.text
        asset = chunk.attached_assets[0]
        assert asset.asset_type == "table"
        assert "Status" in (asset.text_summary or "")
        assert "Idle" in (asset.text_summary or "")

    def test_parse_pdf_pairs_table_caption(self) -> None:
        service = IngestionService(settings=_ingestion_settings())
        result = service.parse_pdf(_single_page_table_pdf(caption_below=True))

        assets = [
            asset
            for chunk in result.chunks
            for asset in chunk.attached_assets
            if asset.asset_type == "table"
        ]
        assert len(assets) == 1
        assert assets[0].figure_number == "2-1"
        assert assets[0].figure_caption == "Table 2-1 Status codes"

    def test_parse_pdf_merges_cross_page_table_fragments(self) -> None:
        service = IngestionService(settings=_ingestion_settings())
        result = service.parse_pdf(_cross_page_table_pdf())

        table_assets = [
            asset
            for chunk in result.chunks
            for asset in chunk.attached_assets
            if asset.asset_type == "table"
        ]
        assert len(table_assets) == 1
        summary = table_assets[0].text_summary or ""
        assert "| A1 | 220V |" in summary
        assert "| A2 | 110V |" in summary
        assert "Model" in summary
        assert "Voltage" in summary
        regions = table_assets[0].layout_regions or []
        assert len(regions) == 2
        assert {region["page"] for region in regions} == {1, 2}

    def test_parse_pdf_gracefully_disables_table_extraction_when_unavailable(self) -> None:
        service = IngestionService(settings=_ingestion_settings())
        with patch(
            "app.services.ingestion.extract_tables_from_page",
            side_effect=AttributeError("no find_tables"),
        ):
            result = service.parse_pdf(_single_page_table_pdf())

        assert result.page_count == 1
        assert any(chunk.text.strip() for chunk in result.chunks)
        assert not any(
            asset.asset_type == "table"
            for chunk in result.chunks
            for asset in chunk.attached_assets
        )

    def test_parse_pdf_attaches_table_by_explicit_reference_not_nearest_text(self) -> None:
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text(
            (50.0, 80.0),
            "See Table 2-1 for the full status list.",
            fontsize=12,
        )
        page.insert_text(
            (50.0, 320.0),
            "Calibration must finish before checking status codes in daily operation.",
            fontsize=12,
        )
        _draw_grid_table(page, top=400.0)
        page.insert_text((50.0, 520.0), "Table 2-1 Status codes", fontsize=10)
        pdf_bytes = doc.tobytes()
        doc.close()

        settings = _ingestion_settings(rag_chunk_size=70, rag_chunk_overlap=0)
        result = IngestionService(settings=settings).parse_pdf(pdf_bytes)

        ref_chunk = next(
            chunk for chunk in result.chunks if "See Table 2-1" in chunk.text
        )
        closer_chunk = next(
            chunk
            for chunk in result.chunks
            if "Calibration must finish" in chunk.text
        )
        table_assets = [
            asset
            for chunk in result.chunks
            for asset in chunk.attached_assets
            if asset.asset_type == "table"
        ]

        assert len(table_assets) == 1
        assert table_assets[0].figure_number == "2-1"
        assert ref_chunk.attached_assets == [table_assets[0]]
        assert closer_chunk.attached_assets == []

    def test_parse_pdf_includes_vlm_promoted_tables(self) -> None:
        promoted = EmbeddedTable(
            page=1,
            section="S1",
            bbox=(20.0, 300.0, 220.0, 420.0),
            sort_key=300.0,
            summary="| 型号 | 电压 |",
            png_bytes=b"promoted-table",
            width=100,
            height=80,
            vlm_caption="VLM 识别的栅格表",
        )

        service = IngestionService(settings=_ingestion_settings())
        with patch(
            "app.services.ingestion.route_figures_via_vlm",
            return_value=([], [promoted]),
        ):
            result = service.parse_pdf(_single_page_table_pdf(with_intro=True))

        promoted_assets = [
            asset
            for chunk in result.chunks
            for asset in chunk.attached_assets
            if asset.text_summary == "| 型号 | 电压 |"
        ]
        assert len(promoted_assets) == 1
        assert promoted_assets[0].asset_type == "table"

    def test_explicit_figure_reference_attaches_before_reading_order(self) -> None:
        doc = fitz.open()
        page = doc.new_page(width=600, height=800)
        page.insert_text(
            (50.0, 80.0),
            "As shown in Figure 4-7, adjust arc time.",
            fontsize=12,
        )
        page.insert_text(
            (50.0, 320.0),
            "The teach pendant screen shows the current value.",
            fontsize=12,
        )
        pdf_bytes = doc.tobytes()
        doc.close()

        figure = EmbeddedFigure(
            page=1,
            section="S1",
            bbox=(50.0, 400.0, 300.0, 560.0),
            sort_key=400.0,
            text="",
            png_bytes=b"figure-png",
            width=120,
            height=90,
            figure_number="4-7",
            caption_text="Figure 4-7 Arc time illustration",
        )

        service = IngestionService(
            settings=_ingestion_settings(rag_chunk_size=70, rag_chunk_overlap=0)
        )
        with patch(
            "app.services.ingestion.extract_figures_from_page",
            return_value=[figure],
        ), patch(
            "app.services.ingestion.extract_tables_from_page",
            return_value=[],
        ), patch(
            "app.services.ingestion.route_figures_via_vlm",
            return_value=([figure], []),
        ):
            result = service.parse_pdf(pdf_bytes)

        ref_chunk = next(
            chunk for chunk in result.chunks if "Figure 4-7" in chunk.text
        )
        nearer_chunk = next(
            chunk
            for chunk in result.chunks
            if "teach pendant screen" in chunk.text
        )
        figure_assets = [
            asset
            for chunk in result.chunks
            for asset in chunk.attached_assets
            if asset.asset_type == "figure"
        ]

        assert len(figure_assets) == 1
        assert figure_assets[0].figure_number == "4-7"
        assert ref_chunk.attached_assets == [figure_assets[0]]
        assert nearer_chunk.attached_assets == []


class TestAttachByExplicitRefsIngestionChunks:
    def test_attaches_numbered_figure_to_mentioning_parsed_chunk(self) -> None:
        chunk = SimpleNamespace(
            chunk_index=0,
            text="Refer to Figure 4-7 for arc settings.",
            attached_assets=[],
        )
        figure = EmbeddedFigure(
            page=2,
            section="S1",
            bbox=(10.0, 100.0, 200.0, 220.0),
            sort_key=100.0,
            text="",
            png_bytes=b"png",
            width=80,
            height=60,
            figure_number="4-7",
            caption_text="Figure 4-7 Arc time illustration",
        )

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [figure], [])

        assert orphan_figures == []
        assert orphan_tables == []
        assert len(chunk.attached_assets) == 1
        assert chunk.attached_assets[0].asset_type == "figure"
        assert chunk.attached_assets[0].figure_number == "4-7"
