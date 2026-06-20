from unittest.mock import patch

from app.config import Settings
from app.services.pdf_table_merge import (
    can_merge_cross_page_tables,
    merge_cross_page_tables,
)
from app.services.pdf_tables import EmbeddedTable
from app.services.table_html import merge_markdown_summaries


def _table(
    *,
    page: int,
    summary: str,
    y0: float,
    y1: float,
    section: str | None = "S1",
    figure_number: str | None = None,
    caption_text: str | None = None,
) -> EmbeddedTable:
    return EmbeddedTable(
        page=page,
        section=section,
        bbox=(10.0, y0, 500.0, y1),
        sort_key=y0,
        summary=summary,
        png_bytes=b"png",
        width=100,
        height=100,
        figure_number=figure_number,
        caption_text=caption_text,
    )


PAGE_HEIGHT = 800.0
PAGE_HEIGHTS = {1: PAGE_HEIGHT, 2: PAGE_HEIGHT}

PAGE1_SUMMARY = "| 型号 | 电压 |\n| --- | --- |\n| A1 | 220V |"
PAGE2_SUMMARY = "| 型号 | 电压 |\n| --- | --- |\n| A2 | 110V |"


class TestMergeMarkdownSummaries:
    def test_drops_repeated_header_on_continuation(self) -> None:
        merged = merge_markdown_summaries([PAGE1_SUMMARY, PAGE2_SUMMARY])
        assert merged.count("| 型号 | 电压 |") == 1
        assert "| A1 | 220V |" in merged
        assert "| A2 | 110V |" in merged


class TestCrossPageMerge:
    def test_merges_bottom_top_fragments(self) -> None:
        settings = Settings()
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0)
        right = _table(
            page=2,
            summary=PAGE2_SUMMARY,
            y0=40.0,
            y1=180.0,
            caption_text="表 3-1 参数",
            figure_number="3-1",
        )
        assert can_merge_cross_page_tables(
            left,
            right,
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

        merged = merge_cross_page_tables(
            [left, right],
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )
        assert len(merged) == 1
        assert merged[0].page == 1
        assert "| A2 | 110V |" in merged[0].summary
        assert merged[0].caption_text == "表 3-1 参数"
        assert merged[0].figure_number == "3-1"
        assert merged[0].layout_regions is not None
        assert len(merged[0].layout_regions) == 2
        assert merged[0].layout_regions[0]["page"] == 1
        assert merged[0].layout_regions[1]["page"] == 2

    def test_single_table_gets_one_layout_region(self) -> None:
        settings = Settings()
        table = _table(page=1, summary=PAGE1_SUMMARY, y0=100.0, y1=300.0)
        merged = merge_cross_page_tables(
            [table],
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )
        assert len(merged) == 1
        assert merged[0].layout_regions is not None
        assert len(merged[0].layout_regions) == 1
        assert merged[0].layout_regions[0]["page"] == 1

    def test_skips_non_consecutive_pages(self) -> None:
        settings = Settings()
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0)
        right = _table(page=3, summary=PAGE2_SUMMARY, y0=40.0, y1=180.0)
        merged = merge_cross_page_tables(
            [left, right],
            page_heights={**PAGE_HEIGHTS, 3: PAGE_HEIGHT},
            settings=settings,
        )
        assert len(merged) == 2

    def test_skips_mismatched_columns_without_figure_number(self) -> None:
        settings = Settings()
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0)
        right = _table(
            page=2,
            summary="| only |",
            y0=40.0,
            y1=180.0,
        )
        assert not can_merge_cross_page_tables(
            left,
            right,
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

    def test_merges_mismatched_columns_when_figure_numbers_match(self) -> None:
        settings = Settings()
        left = _table(
            page=1,
            summary=PAGE1_SUMMARY,
            y0=620.0,
            y1=760.0,
            figure_number="3-1",
        )
        right = _table(
            page=2,
            summary="| only |",
            y0=40.0,
            y1=180.0,
            figure_number="3-1",
        )
        assert can_merge_cross_page_tables(
            left,
            right,
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

        merged = merge_cross_page_tables(
            [left, right],
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )
        assert len(merged) == 1
        assert merged[0].figure_number == "3-1"

    def test_merge_disabled_returns_original_list(self) -> None:
        settings = Settings(pdf_merge_cross_page_tables=False)
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0)
        right = _table(page=2, summary=PAGE2_SUMMARY, y0=40.0, y1=180.0)

        merged = merge_cross_page_tables(
            [left, right],
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

        assert merged == [left, right]

    def test_stitch_failure_falls_back_to_first_png(self) -> None:
        settings = Settings()
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0)
        right = _table(page=2, summary=PAGE2_SUMMARY, y0=40.0, y1=180.0)

        with patch(
            "app.services.pdf_table_merge.stitch_png_bytes_vertically",
            side_effect=RuntimeError("stitch failed"),
        ):
            merged = merge_cross_page_tables(
                [left, right],
                page_heights=PAGE_HEIGHTS,
                settings=settings,
            )

        assert len(merged) == 1
        assert merged[0].png_bytes == left.png_bytes
        assert merged[0].width == left.width
        assert merged[0].height == left.height

    def test_skips_merge_for_different_sections(self) -> None:
        settings = Settings()
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0, section="S1")
        right = _table(
            page=2,
            summary=PAGE2_SUMMARY,
            y0=40.0,
            y1=180.0,
            section="S2",
        )

        assert not can_merge_cross_page_tables(
            left,
            right,
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

    def test_skips_merge_for_mismatched_figure_numbers(self) -> None:
        settings = Settings()
        left = _table(
            page=1,
            summary=PAGE1_SUMMARY,
            y0=620.0,
            y1=760.0,
            figure_number="3-1",
        )
        right = _table(
            page=2,
            summary=PAGE2_SUMMARY,
            y0=40.0,
            y1=180.0,
            figure_number="3-2",
        )

        assert not can_merge_cross_page_tables(
            left,
            right,
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

    def test_skips_merge_when_page_height_missing(self) -> None:
        settings = Settings()
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0)
        right = _table(page=2, summary=PAGE2_SUMMARY, y0=40.0, y1=180.0)

        assert not can_merge_cross_page_tables(
            left,
            right,
            page_heights={1: PAGE_HEIGHT},
            settings=settings,
        )

    def test_skips_merge_when_left_not_near_page_bottom(self) -> None:
        settings = Settings()
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=100.0, y1=240.0)
        right = _table(page=2, summary=PAGE2_SUMMARY, y0=40.0, y1=180.0)

        assert not can_merge_cross_page_tables(
            left,
            right,
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

    def test_skips_merge_when_right_not_near_page_top(self) -> None:
        settings = Settings()
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0)
        right = _table(page=2, summary=PAGE2_SUMMARY, y0=300.0, y1=440.0)

        assert not can_merge_cross_page_tables(
            left,
            right,
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

    def test_stitch_disabled_uses_first_page_png(self) -> None:
        settings = Settings(pdf_stitch_cross_page_table_png=False)
        left = _table(page=1, summary=PAGE1_SUMMARY, y0=620.0, y1=760.0)
        right = _table(page=2, summary=PAGE2_SUMMARY, y0=40.0, y1=180.0)

        merged = merge_cross_page_tables(
            [left, right],
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

        assert len(merged) == 1
        assert merged[0].png_bytes == left.png_bytes

    def test_single_table_preserves_existing_layout_regions(self) -> None:
        settings = Settings()
        regions = ({"page": 1, "bbox": [10.0, 100.0, 500.0, 300.0]},)
        table = _table(page=1, summary=PAGE1_SUMMARY, y0=100.0, y1=300.0)
        table = EmbeddedTable(
            page=table.page,
            section=table.section,
            bbox=table.bbox,
            sort_key=table.sort_key,
            summary=table.summary,
            png_bytes=table.png_bytes,
            width=table.width,
            height=table.height,
            layout_regions=regions,
        )

        merged = merge_cross_page_tables(
            [table],
            page_heights=PAGE_HEIGHTS,
            settings=settings,
        )

        assert merged[0].layout_regions == regions

    def test_empty_input_returns_empty_list(self) -> None:
        assert merge_cross_page_tables([], page_heights=PAGE_HEIGHTS, settings=Settings()) == []
