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

    def test_skips_mismatched_columns(self) -> None:
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
