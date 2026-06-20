import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.services.pdf_tables import (
    EmbeddedTable,
    _embedded_table_from_fitz_table,
    _render_table_png,
    _table_summary,
    attach_tables_to_chunks,
    extract_tables_from_page,
    filter_page_blocks,
    filter_page_text,
    table_bboxes_on_page,
)


def _fitz_table(*, bbox: tuple[float, float, float, float], rows: int, cols: int, summary: str):
    table = MagicMock()
    table.row_count = rows
    table.col_count = cols
    table.bbox = bbox
    table.to_markdown.return_value = summary
    return table


class TestExtractTablesFromPage:
    def test_uses_default_find_tables_first(self) -> None:
        page = MagicMock()
        default_table = _fitz_table(
            bbox=(10.0, 20.0, 500.0, 200.0),
            rows=3,
            cols=2,
            summary="| A | B |\n| --- | --- |\n| 1 | 2 |",
        )
        default_finder = MagicMock()
        default_finder.tables = [default_table]
        page.find_tables.return_value = default_finder

        settings = Settings(pdf_table_header_detect_enabled=False)
        section_resolver = lambda page_number, y: "S1"

        with patch(
            "app.services.pdf_tables._render_table_png",
            return_value=(b"png", 100, 80),
        ):
            tables = extract_tables_from_page(
                page,
                1,
                settings=settings,
                section_resolver=section_resolver,
            )

        assert len(tables) == 1
        assert tables[0].summary.startswith("| A | B |")
        page.find_tables.assert_called_once_with()

    def test_falls_back_to_header_guided_when_default_empty(self) -> None:
        page = MagicMock()
        default_finder = MagicMock()
        default_finder.tables = []
        header_table = _fitz_table(
            bbox=(2.0, 95.0, 388.0, 700.0),
            rows=4,
            cols=3,
            summary="| 第一级 | 第二级 | 功能说明 |",
        )
        header_finder = MagicMock()
        header_finder.tables = [header_table]
        page.find_tables.side_effect = [default_finder, header_finder]

        settings = Settings(pdf_table_header_detect_enabled=True)
        section_resolver = lambda page_number, y: "S1"

        region = MagicMock()
        region.headers = ("第一级", "第二级", "功能说明")
        region.vertical_lines = (2.0, 85.0, 210.0, 388.0)
        region.clip = MagicMock()

        with patch(
            "app.services.pdf_tables.discover_header_table_regions",
            return_value=[region],
        ), patch(
            "app.services.pdf_tables._render_table_png",
            return_value=(b"png", 100, 80),
        ):
            tables = extract_tables_from_page(
                page,
                50,
                settings=settings,
                section_resolver=section_resolver,
            )

        assert len(tables) == 1
        assert page.find_tables.call_count == 2

    def test_skips_header_tables_overlapping_default(self) -> None:
        page = MagicMock()
        default_table = _fitz_table(
            bbox=(10.0, 20.0, 500.0, 200.0),
            rows=3,
            cols=2,
            summary="| A | B |\n| --- | --- |\n| 1 | 2 |",
        )
        default_finder = MagicMock()
        default_finder.tables = [default_table]
        page.find_tables.return_value = default_finder

        settings = Settings(pdf_table_header_detect_enabled=True)
        section_resolver = lambda page_number, y: "S1"

        with patch(
            "app.services.pdf_tables.discover_header_table_regions",
        ) as discover:
            tables = extract_tables_from_page(
                page,
                1,
                settings=settings,
                section_resolver=section_resolver,
            )

        assert len(tables) == 1
        discover.assert_not_called()
        page.find_tables.assert_called_once_with()

    def test_returns_empty_when_table_extraction_disabled(self) -> None:
        page = MagicMock()
        settings = Settings(pdf_extract_tables=False)
        section_resolver = lambda page_number, y: "S1"

        tables = extract_tables_from_page(
            page,
            1,
            settings=settings,
            section_resolver=section_resolver,
        )

        assert tables == []
        page.find_tables.assert_not_called()

    def test_skips_header_guided_when_disabled(self) -> None:
        page = MagicMock()
        default_finder = MagicMock()
        default_finder.tables = []
        page.find_tables.return_value = default_finder

        settings = Settings(pdf_table_header_detect_enabled=False)
        section_resolver = lambda page_number, y: "S1"

        with patch(
            "app.services.pdf_tables.discover_header_table_regions",
        ) as discover:
            tables = extract_tables_from_page(
                page,
                1,
                settings=settings,
                section_resolver=section_resolver,
            )

        assert tables == []
        discover.assert_not_called()
        page.find_tables.assert_called_once_with()

    def test_header_guided_continues_when_find_tables_raises(self) -> None:
        page = MagicMock()
        default_finder = MagicMock()
        default_finder.tables = []
        header_table = _fitz_table(
            bbox=(2.0, 95.0, 388.0, 700.0),
            rows=4,
            cols=3,
            summary="| 状态 | 说明 |",
        )
        header_finder = MagicMock()
        header_finder.tables = [header_table]
        page.find_tables.side_effect = [default_finder, RuntimeError("boom"), header_finder]

        settings = Settings(pdf_table_header_detect_enabled=True)
        section_resolver = lambda page_number, y: "S1"

        region_a = MagicMock()
        region_a.headers = ("第一级", "第二级", "功能说明")
        region_a.vertical_lines = (2.0, 85.0, 210.0, 388.0)
        region_a.clip = MagicMock()
        region_b = MagicMock()
        region_b.headers = ("状态", "说明")
        region_b.vertical_lines = (10.0, 250.0)
        region_b.clip = MagicMock()

        with patch(
            "app.services.pdf_tables.discover_header_table_regions",
            return_value=[region_a, region_b],
        ), patch(
            "app.services.pdf_tables._render_table_png",
            return_value=(b"png", 100, 80),
        ):
            tables = extract_tables_from_page(
                page,
                3,
                settings=settings,
                section_resolver=section_resolver,
            )

        assert len(tables) == 1
        assert tables[0].summary.startswith("| 状态 | 说明 |")
        assert page.find_tables.call_count == 3

    def test_skips_tables_below_min_dimensions(self) -> None:
        page = MagicMock()
        tiny_table = _fitz_table(
            bbox=(10.0, 20.0, 100.0, 40.0),
            rows=1,
            cols=1,
            summary="| A |",
        )
        default_finder = MagicMock()
        default_finder.tables = [tiny_table]
        page.find_tables.return_value = default_finder

        settings = Settings(
            pdf_table_min_rows=2,
            pdf_table_min_cols=2,
            pdf_table_header_detect_enabled=False,
        )
        section_resolver = lambda page_number, y: "S1"

        tables = extract_tables_from_page(
            page,
            1,
            settings=settings,
            section_resolver=section_resolver,
        )

        assert tables == []

    def test_raises_when_find_tables_unavailable(self) -> None:
        page = MagicMock()
        page.find_tables.side_effect = AttributeError("no find_tables")
        settings = Settings()
        section_resolver = lambda page_number, y: "S1"

        with pytest.raises(AttributeError, match="PyMuPDF find_tables is unavailable"):
            extract_tables_from_page(
                page,
                1,
                settings=settings,
                section_resolver=section_resolver,
            )


class TestEmbeddedTableFromFitzTable:
    def test_skips_empty_summary(self) -> None:
        page = MagicMock()
        table = MagicMock()
        table.row_count = 3
        table.col_count = 2
        table.bbox = (10.0, 20.0, 500.0, 200.0)
        table.to_markdown.return_value = "   "
        table.extract.return_value = []

        settings = Settings()
        section_resolver = lambda page_number, y: "S1"

        result = _embedded_table_from_fitz_table(
            page,
            table,
            page_number=1,
            scale=2.0,
            settings=settings,
            section_resolver=section_resolver,
        )

        assert result is None

    def test_skips_table_when_render_fails(self) -> None:
        page = MagicMock()
        table = MagicMock()
        table.row_count = 3
        table.col_count = 2
        table.bbox = (10.0, 20.0, 500.0, 200.0)
        table.to_markdown.return_value = "| A | B |"

        settings = Settings()
        section_resolver = lambda page_number, y: "S1"

        with patch(
            "app.services.pdf_tables._render_table_png",
            side_effect=RuntimeError("render failed"),
        ):
            result = _embedded_table_from_fitz_table(
                page,
                table,
                page_number=1,
                scale=2.0,
                settings=settings,
                section_resolver=section_resolver,
            )

        assert result is None

    def test_falls_back_to_extract_when_markdown_empty(self) -> None:
        page = MagicMock()
        table = MagicMock()
        table.row_count = 3
        table.col_count = 2
        table.bbox = (10.0, 20.0, 500.0, 200.0)
        table.to_markdown.return_value = ""
        table.extract.return_value = [["A", "B"], ["1", "2"]]

        settings = Settings()
        section_resolver = lambda page_number, y: "S1"

        with patch(
            "app.services.pdf_tables._render_table_png",
            return_value=(b"png", 100, 80),
        ):
            result = _embedded_table_from_fitz_table(
                page,
                table,
                page_number=1,
                scale=2.0,
                settings=settings,
                section_resolver=section_resolver,
            )

        assert result is not None
        assert result.summary == "A | B\n1 | 2"

    def test_skips_zero_area_bbox(self) -> None:
        page = MagicMock()
        table = MagicMock()
        table.row_count = 3
        table.col_count = 2
        table.bbox = (10.0, 20.0, 10.0, 20.0)
        table.to_markdown.return_value = "| A | B |"

        settings = Settings()
        section_resolver = lambda page_number, y: "S1"

        result = _embedded_table_from_fitz_table(
            page,
            table,
            page_number=1,
            scale=2.0,
            settings=settings,
            section_resolver=section_resolver,
        )

        assert result is None


class TestTableSummary:
    def test_uses_markdown_when_available(self) -> None:
        table = MagicMock()
        table.to_markdown.return_value = "| H1 | H2 |"
        assert _table_summary(table) == "| H1 | H2 |"

    def test_falls_back_to_extract_rows(self) -> None:
        table = MagicMock()
        table.to_markdown.side_effect = RuntimeError("no markdown")
        table.extract.return_value = [["X", None], [None, "Y"]]
        assert _table_summary(table) == "X | \n | Y"

    def test_returns_empty_when_both_sources_fail(self) -> None:
        table = MagicMock()
        table.to_markdown.side_effect = RuntimeError("no markdown")
        table.extract.side_effect = RuntimeError("no extract")
        assert _table_summary(table) == ""


class TestFilterPageBlocks:
    def test_excludes_overlapping_table_regions_and_sorts_blocks(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [
            (0, 200, 500, 240, "正文段落"),
            (0, 50, 500, 180, "表格区域文字"),
            (0, 100, 500, 130, "图 3-1 示例"),
            (0, 300, 500, 320, ""),
            (0, 10, 20),
        ]

        blocks = filter_page_blocks(
            page,
            exclude_bboxes=[(0.0, 50.0, 500.0, 180.0)],
        )

        assert blocks == [(0.0, 200.0, 500.0, 240.0, "正文段落")]

    def test_filter_page_text_joins_remaining_blocks(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [
            (0, 200, 500, 240, "第一段"),
            (0, 260, 500, 300, "第二段"),
        ]

        text = filter_page_text(page, exclude_bboxes=[])

        assert text == "第一段\n第二段"

    def test_filter_page_text_returns_empty_when_no_blocks(self) -> None:
        page = MagicMock()
        page.get_text.return_value = []

        assert filter_page_text(page, exclude_bboxes=[]) == ""

    def test_excludes_caption_blocks(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [
            (0, 200, 500, 240, "正文段落"),
            (0, 260, 500, 300, "表 2-1 额定参数表"),
        ]

        blocks = filter_page_blocks(page, exclude_bboxes=[])

        assert blocks == [(0.0, 200.0, 500.0, 240.0, "正文段落")]

    def test_excludes_header_footer_blocks(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [
            (0, 10, 500, 30, "页眉文字"),
            (0, 200, 500, 240, "正文段落"),
        ]

        with patch(
            "app.services.pdf_header_footer.should_drop_block",
            side_effect=lambda bbox, text, _page, _hf: text == "页眉文字",
        ):
            blocks = filter_page_blocks(page, exclude_bboxes=[])

        assert blocks == [(0.0, 200.0, 500.0, 240.0, "正文段落")]


class TestRenderTablePng:
    def test_renders_clip_region_from_page(self) -> None:
        import fitz

        doc = fitz.open()
        try:
            page = doc.new_page(width=200, height=200)
            page.draw_rect(fitz.Rect(20, 20, 120, 80), color=(0, 0, 0), fill=(1, 1, 1))

            png_bytes, width, height = _render_table_png(
                page,
                (20.0, 20.0, 120.0, 80.0),
                scale=2.0,
            )
        finally:
            doc.close()

        assert png_bytes.startswith(b"\x89PNG")
        assert width > 0
        assert height > 0


class TestTableBboxesOnPage:
    def test_returns_only_matching_page_bboxes(self) -> None:
        tables = [
            EmbeddedTable(
                page=1,
                section=None,
                bbox=(1.0, 2.0, 3.0, 4.0),
                sort_key=2.0,
                summary="a",
                png_bytes=b"png",
                width=1,
                height=1,
            ),
            EmbeddedTable(
                page=2,
                section=None,
                bbox=(5.0, 6.0, 7.0, 8.0),
                sort_key=6.0,
                summary="b",
                png_bytes=b"png",
                width=1,
                height=1,
            ),
        ]

        assert table_bboxes_on_page(tables, 1) == [(1.0, 2.0, 3.0, 4.0)]


class TestAttachTablesToChunks:
    def test_attaches_table_to_preceding_chunk_and_returns_orphans(self) -> None:
        chunk = SimpleNamespace(
            chunk_index=0,
            page=1,
            text="表前说明",
            section="S1",
            sort_key=100.0,
            layout_y1=180.0,
            layout_bbox=(0.0, 100.0, 500.0, 180.0),
            attached_assets=[],
        )
        orphan_chunk = SimpleNamespace(
            chunk_index=1,
            page=2,
            text="另一页",
            section="S2",
            sort_key=50.0,
            layout_y1=120.0,
            layout_bbox=(0.0, 50.0, 500.0, 120.0),
            attached_assets=[],
        )
        attached_table = EmbeddedTable(
            page=1,
            section="S1",
            bbox=(10.0, 200.0, 500.0, 400.0),
            sort_key=200.0,
            summary="| A | B |",
            png_bytes=b"png",
            width=100,
            height=80,
        )
        orphan_table = EmbeddedTable(
            page=5,
            section="S5",
            bbox=(10.0, 50.0, 500.0, 200.0),
            sort_key=50.0,
            summary="| C | D |",
            png_bytes=b"png",
            width=100,
            height=80,
        )

        orphans = attach_tables_to_chunks(
            [attached_table, orphan_table],
            [chunk, orphan_chunk],
        )

        assert len(chunk.attached_assets) == 1
        assert chunk.attached_assets[0].asset_type == "table"
        assert chunk.attached_assets[0].text_summary == "| A | B |"
        assert orphans == [orphan_table]

    def test_attached_asset_includes_layout_regions(self) -> None:
        chunk = SimpleNamespace(
            chunk_index=0,
            page=2,
            text="说明",
            section="S1",
            sort_key=80.0,
            layout_y1=140.0,
            layout_bbox=(0.0, 80.0, 500.0, 140.0),
            attached_assets=[],
        )
        table = EmbeddedTable(
            page=2,
            section="S1",
            bbox=(10.0, 160.0, 500.0, 320.0),
            sort_key=160.0,
            summary="| A | B |",
            png_bytes=b"png",
            width=100,
            height=80,
            layout_regions=({"page": 2, "bbox": [10.0, 160.0, 500.0, 320.0]},),
        )

        orphans = attach_tables_to_chunks([table], [chunk])

        assert orphans == []
        assert chunk.attached_assets[0].layout_regions == [
            {"page": 2, "bbox": [10.0, 160.0, 500.0, 320.0]},
        ]


class TestExtractTablesHeaderGuidedMultiRegion:
    def test_finds_multiple_non_overlapping_header_regions(self) -> None:
        page = MagicMock()
        default_finder = MagicMock()
        default_finder.tables = []

        table_a = _fitz_table(
            bbox=(2.0, 95.0, 200.0, 300.0),
            rows=3,
            cols=2,
            summary="| 状态 | 说明 |",
        )
        table_b = _fitz_table(
            bbox=(210.0, 95.0, 388.0, 300.0),
            rows=3,
            cols=2,
            summary="| 参数 | 数值 |",
        )
        finder_a = MagicMock()
        finder_a.tables = [table_a]
        finder_b = MagicMock()
        finder_b.tables = [table_b]
        page.find_tables.side_effect = [default_finder, finder_a, finder_b]

        settings = Settings(pdf_table_header_detect_enabled=True)
        section_resolver = lambda page_number, y: "S1"

        region_a = MagicMock()
        region_a.headers = ("状态", "说明")
        region_a.vertical_lines = (2.0, 100.0)
        region_a.clip = MagicMock()
        region_b = MagicMock()
        region_b.headers = ("参数", "数值")
        region_b.vertical_lines = (210.0, 388.0)
        region_b.clip = MagicMock()

        with patch(
            "app.services.pdf_tables.discover_header_table_regions",
            return_value=[region_a, region_b],
        ), patch(
            "app.services.pdf_tables._render_table_png",
            return_value=(b"png", 100, 80),
        ):
            tables = extract_tables_from_page(
                page,
                4,
                settings=settings,
                section_resolver=section_resolver,
            )

        assert len(tables) == 2
        summaries = {table.summary for table in tables}
        assert "| 状态 | 说明 |" in summaries
        assert "| 参数 | 数值 |" in summaries
