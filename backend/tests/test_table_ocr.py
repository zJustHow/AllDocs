from app.config import Settings
from app.services.table_html import html_table_to_markdown, parse_html_table
from app.services.table_ocr import TableOCRResult, is_table_structure_candidate


SAMPLE_HTML = (
    "<html><body><table>"
    "<tr><td>型号</td><td>电压</td></tr>"
    "<tr><td>A1</td><td>220V</td></tr>"
    "<tr><td>A2</td><td>110V</td></tr>"
    "</table></body></html>"
)


class TestTableHtml:
    def test_parse_html_table_counts(self) -> None:
        rows, row_count, col_count, filled = parse_html_table(SAMPLE_HTML)
        assert row_count == 3
        assert col_count == 2
        assert filled == 6
        assert rows[0] == ["型号", "电压"]

    def test_html_table_to_markdown(self) -> None:
        markdown = html_table_to_markdown(SAMPLE_HTML)
        assert "| 型号 | 电压 |" in markdown
        assert "| A1 | 220V |" in markdown


class TestTableStructureCandidate:
    def test_accepts_well_filled_table(self) -> None:
        settings = Settings()
        result = TableOCRResult(
            summary=html_table_to_markdown(SAMPLE_HTML),
            row_count=3,
            col_count=2,
            filled_cells=6,
            score=0.0,
        )
        assert is_table_structure_candidate(result, settings)

    def test_rejects_insufficient_filled_cells(self) -> None:
        settings = Settings()
        result = TableOCRResult(
            summary="| a |",
            row_count=2,
            col_count=2,
            filled_cells=1,
            score=0.0,
        )
        assert not is_table_structure_candidate(result, settings)

    def test_accepts_minimum_filled_cells(self) -> None:
        settings = Settings()
        result = TableOCRResult(
            summary="| a | b |",
            row_count=2,
            col_count=2,
            filled_cells=2,
            score=0.0,
        )
        assert is_table_structure_candidate(result, settings)

    def test_accepts_tall_single_column_table(self) -> None:
        settings = Settings()
        result = TableOCRResult(
            summary="| a |\n| --- |\n| 1 |\n| 2 |\n| 3 |",
            row_count=4,
            col_count=1,
            filled_cells=4,
            score=0.0,
        )
        assert is_table_structure_candidate(result, settings)

    def test_accepts_wide_single_row_table(self) -> None:
        settings = Settings()
        result = TableOCRResult(
            summary="| a | b | c | d |",
            row_count=1,
            col_count=4,
            filled_cells=4,
            score=0.0,
        )
        assert is_table_structure_candidate(result, settings)

    def test_rejects_single_cell(self) -> None:
        settings = Settings(
            pdf_table_min_rows=2,
            pdf_table_min_cols=2,
            ocr_table_min_filled_cells=1,
        )
        result = TableOCRResult(
            summary="| only |",
            row_count=1,
            col_count=1,
            filled_cells=1,
            score=0.0,
        )
        assert not is_table_structure_candidate(result, settings)
