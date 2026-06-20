from unittest.mock import MagicMock, patch

import fitz

from app.config import Settings
from app.services.pdf_table_header_detect import (
    HeaderTableRegion,
    clip_from_headers,
    discover_header_table_regions,
    find_header_row,
    find_tables_for_region,
    section_boundary_y,
    vertical_lines_from_headers,
)


def _rect(x0: float, y0: float, x1: float, y1: float) -> fitz.Rect:
    return fitz.Rect(x0, y0, x1, y1)


class TestFindHeaderRow:
    def test_finds_headers_on_same_row(self) -> None:
        page = MagicMock()
        page.search_for.side_effect = [
            [_rect(10, 100, 50, 115)],
            [_rect(120, 102, 170, 117)],
            [_rect(300, 101, 380, 116)],
        ]
        row = find_header_row(page, ("第一级", "第二级", "功能说明"), y_tolerance=10.0)
        assert row is not None
        assert [rect.x0 for rect in row] == [10.0, 120.0, 300.0]

    def test_rejects_missing_header(self) -> None:
        page = MagicMock()
        page.search_for.side_effect = [[_rect(10, 100, 50, 115)], []]
        assert find_header_row(page, ("第一级", "第二级"), y_tolerance=10.0) is None

    def test_rejects_headers_on_different_rows(self) -> None:
        page = MagicMock()
        page.search_for.side_effect = [
            [_rect(10, 100, 50, 115)],
            [_rect(120, 200, 170, 215)],
        ]
        assert find_header_row(page, ("第一级", "第二级"), y_tolerance=5.0) is None

    def test_tries_next_anchor_when_first_row_incomplete(self) -> None:
        page = MagicMock()
        page.search_for.side_effect = [
            [_rect(10, 100, 50, 115), _rect(10, 500, 50, 515)],
            [_rect(120, 200, 170, 215), _rect(120, 502, 170, 517)],
        ]
        row = find_header_row(page, ("第一级", "第二级"), y_tolerance=5.0)
        assert row is not None
        assert [rect.x0 for rect in row] == [10.0, 120.0]
        assert row[0].y0 == 500.0

    def test_returns_none_when_all_anchors_fail(self) -> None:
        page = MagicMock()
        page.search_for.side_effect = [
            [_rect(10, 100, 50, 115), _rect(10, 500, 50, 515)],
            [_rect(120, 200, 170, 215)],
        ]
        assert find_header_row(page, ("第一级", "第二级"), y_tolerance=5.0) is None


class TestVerticalLinesFromHeaders:
    def test_builds_column_boundaries(self) -> None:
        rects = [_rect(10, 100, 50, 115), _rect(120, 100, 170, 115), _rect(300, 100, 380, 115)]
        lines = vertical_lines_from_headers(rects, margin=8.0)
        assert lines == [2.0, 85.0, 235.0, 388.0]

    def test_returns_empty_for_no_rects(self) -> None:
        assert vertical_lines_from_headers([], margin=8.0) == []


class TestSectionBoundaryY:
    def test_finds_numbered_heading_below(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [
            (0, 100, 500, 120, "第一级  第二级  功能说明"),
            (0, 400, 500, 420, "4.6 机器人状态及报警历史查看"),
        ]
        assert section_boundary_y(page, 150.0) == 400.0

    def test_returns_none_when_no_heading(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [(0, 100, 500, 120, "普通正文")]
        assert section_boundary_y(page, 50.0) is None

    def test_skips_short_blocks(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [
            (0, 400, 500, 420),
            (0, 400, 500, 420, "4.6 标题"),
        ]
        assert section_boundary_y(page, 150.0) == 400.0


class TestClipFromHeaders:
    def test_uses_section_heading_for_bottom(self) -> None:
        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 600, 800)
        settings = Settings()
        header_rects = [_rect(10, 100, 50, 115), _rect(120, 100, 170, 115)]
        vertical_lines = [2.0, 85.0, 178.0]
        with patch(
            "app.services.pdf_table_header_detect.section_boundary_y",
            return_value=500.0,
        ):
            clip = clip_from_headers(page, header_rects, vertical_lines, settings=settings)
        assert clip.x0 == 2.0
        assert clip.x1 == 178.0
        assert clip.y0 == 95.0
        assert clip.y1 == 500.0

    def test_falls_back_to_bottom_ratio_without_section_heading(self) -> None:
        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 600, 800)
        settings = Settings(pdf_table_header_clip_bottom_ratio=0.88)
        header_rects = [_rect(10, 100, 50, 115), _rect(120, 100, 170, 115)]
        vertical_lines = [2.0, 85.0, 178.0]
        with patch(
            "app.services.pdf_table_header_detect.section_boundary_y",
            return_value=None,
        ):
            clip = clip_from_headers(page, header_rects, vertical_lines, settings=settings)
        assert clip.y1 == 704.0

    def test_clamps_top_to_page_origin(self) -> None:
        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 600, 800)
        settings = Settings(pdf_table_header_top_padding=20.0)
        header_rects = [_rect(10, 5, 50, 15), _rect(120, 5, 170, 15)]
        vertical_lines = [2.0, 85.0, 178.0]
        with patch(
            "app.services.pdf_table_header_detect.section_boundary_y",
            return_value=500.0,
        ):
            clip = clip_from_headers(page, header_rects, vertical_lines, settings=settings)
        assert clip.y0 == 0.0


class TestDiscoverHeaderTableRegions:
    def test_discovers_region_for_matching_headers(self) -> None:
        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 600, 800)
        settings = Settings()

        header_rects = [
            _rect(10, 100, 50, 115),
            _rect(120, 100, 170, 115),
            _rect(300, 100, 380, 115),
        ]

        with patch(
            "app.services.pdf_table_header_detect.find_header_row",
            side_effect=[header_rects, None, None, None, None, None, None, None],
        ), patch(
            "app.services.pdf_table_header_detect.section_boundary_y",
            return_value=700.0,
        ):
            regions = discover_header_table_regions(page, settings=settings)

        assert len(regions) == 1
        assert regions[0].headers == ("第一级", "第二级", "功能说明")
        assert len(regions[0].vertical_lines) == 4
        assert regions[0].clip.y1 == 700.0

    def test_deduplicates_regions_with_same_column_lines(self) -> None:
        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 600, 800)
        settings = Settings()

        shared_rects = [
            _rect(10, 100, 50, 115),
            _rect(120, 100, 170, 115),
        ]

        with patch(
            "app.services.pdf_table_header_detect.find_header_row",
            side_effect=[shared_rects, shared_rects, None, None, None, None, None, None],
        ), patch(
            "app.services.pdf_table_header_detect.section_boundary_y",
            return_value=700.0,
        ):
            regions = discover_header_table_regions(page, settings=settings)

        assert len(regions) == 1

    def test_skips_region_when_vertical_lines_insufficient(self) -> None:
        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 600, 800)
        settings = Settings()
        header_rects = [_rect(10, 100, 50, 115), _rect(120, 100, 170, 115)]

        with patch(
            "app.services.pdf_table_header_detect.find_header_row",
            side_effect=[header_rects, None, None, None, None, None, None, None],
        ), patch(
            "app.services.pdf_table_header_detect.vertical_lines_from_headers",
            return_value=[42.0],
        ):
            regions = discover_header_table_regions(page, settings=settings)

        assert regions == []

    def test_skips_region_with_invalid_clip(self) -> None:
        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 600, 800)
        settings = Settings()
        header_rects = [_rect(10, 100, 50, 115), _rect(120, 100, 170, 115)]

        with patch(
            "app.services.pdf_table_header_detect.find_header_row",
            side_effect=[header_rects, None, None, None, None, None, None, None],
        ), patch(
            "app.services.pdf_table_header_detect.clip_from_headers",
            return_value=_rect(10.0, 100.0, 10.0, 100.0),
        ):
            regions = discover_header_table_regions(page, settings=settings)

        assert regions == []

    def test_sorts_regions_top_to_bottom(self) -> None:
        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 600, 800)
        settings = Settings()

        upper_rects = [_rect(10, 100, 50, 115), _rect(120, 100, 170, 115)]
        lower_rects = [_rect(200, 400, 240, 415), _rect(310, 400, 360, 415)]

        def _clip_for(rects: list[fitz.Rect]) -> fitz.Rect:
            top = min(rect.y0 for rect in rects) - settings.pdf_table_header_top_padding
            bottom = max(rect.y1 for rect in rects) + 200.0
            return fitz.Rect(2.0, top, 178.0, bottom)

        with patch(
            "app.services.pdf_table_header_detect.find_header_row",
            side_effect=[upper_rects, lower_rects, None, None, None, None, None, None],
        ), patch(
            "app.services.pdf_table_header_detect.section_boundary_y",
            return_value=None,
        ), patch(
            "app.services.pdf_table_header_detect.clip_from_headers",
            side_effect=lambda _page, rects, _lines, *, settings: _clip_for(rects),
        ):
            regions = discover_header_table_regions(page, settings=settings)

        assert len(regions) == 2
        assert regions[0].clip.y0 < regions[1].clip.y0


class TestFindTablesForRegion:
    def test_passes_clip_vertical_lines_and_tolerance_settings(self) -> None:
        page = MagicMock()
        settings = Settings(
            pdf_table_header_snap_y_tolerance=6.0,
            pdf_table_header_join_y_tolerance=4.0,
        )
        region = HeaderTableRegion(
            headers=("状态", "说明"),
            vertical_lines=(2.0, 85.0, 178.0),
            clip=_rect(2.0, 95.0, 178.0, 700.0),
        )

        find_tables_for_region(page, region, settings=settings)

        page.find_tables.assert_called_once_with(
            clip=region.clip,
            vertical_lines=[2.0, 85.0, 178.0],
            horizontal_strategy="text",
            min_words_horizontal=1,
            snap_y_tolerance=6.0,
            join_y_tolerance=4.0,
        )


class TestSectionBoundaryEdgeCases:
    def test_skips_headings_at_or_above_reference_y(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [
            (0, 100, 500, 120, "4.5 heading above"),
            (0, 200, 500, 220, "4.6 heading below"),
        ]
        assert section_boundary_y(page, 199.0) is None
        assert section_boundary_y(page, 150.0) == 200.0

    def test_ignores_non_numbered_blocks(self) -> None:
        page = MagicMock()
        page.get_text.return_value = [
            (0, 200, 500, 220, "普通正文"),
            (0, 300, 500, 320, "4.7 numbered heading"),
        ]
        assert section_boundary_y(page, 150.0) == 300.0


class TestFindHeaderRowEdgeCases:
    def test_rejects_candidate_outside_y_tolerance(self) -> None:
        page = MagicMock()
        page.search_for.side_effect = [
            [_rect(10, 100, 50, 115)],
            [_rect(120, 200, 170, 215)],
        ]
        assert find_header_row(page, ("第一级", "第二级"), y_tolerance=5.0) is None
