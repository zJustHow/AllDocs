from types import SimpleNamespace

from app.services.pdf_embedded_images import EmbeddedFigure, ParsedAttachedAsset
from app.services.pdf_refs import attach_by_explicit_refs, extract_figure_refs
from app.services.pdf_tables import EmbeddedTable


def _text_chunk(*, text: str, chunk_index: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        chunk_index=chunk_index,
        text=text,
        attached_assets=[],
    )


def _numbered_table(
    *,
    figure_number: str = "2-1",
    page: int = 3,
    y0: float = 200.0,
) -> EmbeddedTable:
    return EmbeddedTable(
        page=page,
        section="S1",
        bbox=(10.0, y0, 500.0, y0 + 120.0),
        sort_key=y0,
        summary="| A | B |",
        png_bytes=b"table-png",
        width=100,
        height=80,
        figure_number=figure_number,
        caption_text=f"Table {figure_number} Status codes",
    )


def _numbered_figure(
    *,
    figure_number: str = "4-7",
    page: int = 5,
    y0: float = 300.0,
) -> EmbeddedFigure:
    return EmbeddedFigure(
        page=page,
        section="S1",
        bbox=(20.0, y0, 420.0, y0 + 180.0),
        sort_key=y0,
        text="",
        png_bytes=b"figure-png",
        width=120,
        height=90,
        figure_number=figure_number,
        caption_text=f"Figure {figure_number} Illustration",
    )


class TestAttachByExplicitRefs:
    def test_attaches_table_by_forward_reference(self) -> None:
        chunk = _text_chunk(text="Refer to Table 2-1 for rated parameters.")
        table = _numbered_table()

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [], [table])

        assert orphan_figures == []
        assert orphan_tables == []
        assert len(chunk.attached_assets) == 1
        assert chunk.attached_assets[0].asset_type == "table"
        assert chunk.attached_assets[0].figure_number == "2-1"
        assert chunk.attached_assets[0].text_summary == "| A | B |"

    def test_attaches_figure_by_forward_reference(self) -> None:
        chunk = _text_chunk(text="As shown in Figure 4-7, adjust arc time.")
        figure = _numbered_figure()

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [figure], [])

        assert orphan_figures == []
        assert orphan_tables == []
        assert len(chunk.attached_assets) == 1
        assert chunk.attached_assets[0].asset_type == "figure"
        assert chunk.attached_assets[0].figure_number == "4-7"

    def test_attaches_by_chinese_table_reference(self) -> None:
        chunk = _text_chunk(text="参数见表 2-1。")
        table = _numbered_table()

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [], [table])

        assert orphan_figures == []
        assert orphan_tables == []
        assert chunk.attached_assets[0].figure_number == "2-1"

    def test_returns_unreferenced_assets_as_orphans(self) -> None:
        chunk = _text_chunk(text="No numbered references here.")
        table = _numbered_table()
        figure = _numbered_figure()

        orphan_figures, orphan_tables = attach_by_explicit_refs(
            [chunk],
            [figure],
            [table],
        )

        assert orphan_figures == [figure]
        assert orphan_tables == [table]
        assert chunk.attached_assets == []

    def test_skips_assets_without_figure_number(self) -> None:
        chunk = _text_chunk(text="See Table 2-1 below.")
        table = _numbered_table(figure_number="2-1")
        unnumbered = EmbeddedTable(
            page=4,
            section="S1",
            bbox=(10.0, 100.0, 500.0, 220.0),
            sort_key=100.0,
            summary="| X | Y |",
            png_bytes=b"png",
            width=10,
            height=10,
        )

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [], [table, unnumbered])

        assert orphan_figures == []
        assert orphan_tables == [unnumbered]
        assert len(chunk.attached_assets) == 1

    def test_attaches_each_numbered_asset_once(self) -> None:
        first = _text_chunk(text="See Table 2-1 for parameters.", chunk_index=0)
        second = _text_chunk(text="Table 2-1 also lists alarm codes.", chunk_index=1)
        table = _numbered_table()

        orphan_figures, orphan_tables = attach_by_explicit_refs([first, second], [], [table])

        assert orphan_figures == []
        assert orphan_tables == []
        assert len(first.attached_assets) == 1
        assert second.attached_assets == []

    def test_reverse_index_attaches_when_body_mentions_caption_number(self) -> None:
        chunk = _text_chunk(text="状态代码详见表 2-1 所示。")
        table = _numbered_table()

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [], [table])

        assert orphan_figures == []
        assert orphan_tables == []
        assert chunk.attached_assets[0].figure_number == "2-1"

    def test_ignores_forward_reference_without_matching_asset(self) -> None:
        chunk = _text_chunk(text="See Table 9-9 for unknown data.")
        table = _numbered_table(figure_number="2-1")

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [], [table])

        assert chunk.attached_assets == []
        assert orphan_tables == [table]

    def test_uses_first_asset_when_duplicate_figure_numbers_exist(self) -> None:
        chunk = _text_chunk(text="Refer to Table 2-1.")
        first = _numbered_table(figure_number="2-1", page=1, y0=100.0)
        second = _numbered_table(figure_number="2-1", page=2, y0=200.0)

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [], [first, second])

        assert len(chunk.attached_assets) == 1
        assert chunk.attached_assets[0].page == 1
        assert orphan_tables == [second]

    def test_does_not_attach_twice_when_chunk_already_has_numbered_asset(self) -> None:
        chunk = _text_chunk(text="See Table 2-1 for details.")
        chunk.attached_assets.append(
            ParsedAttachedAsset(
                asset_type="table",
                page=1,
                bbox=(1.0, 2.0, 3.0, 4.0),
                png_bytes=b"png",
                width=1,
                height=1,
                figure_number="2-1",
            )
        )
        table = _numbered_table()

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [], [table])

        assert len(chunk.attached_assets) == 1
        assert orphan_tables == []

    def test_reverse_index_skips_already_claimed_asset_in_same_pass(self) -> None:
        first = _text_chunk(text="See Table 2-1 for overview.", chunk_index=0)
        second = _text_chunk(text="表 2-1 所示。", chunk_index=1)
        table = _numbered_table()

        orphan_figures, orphan_tables = attach_by_explicit_refs([first, second], [], [table])

        assert len(first.attached_assets) == 1
        assert second.attached_assets == []
        assert orphan_tables == []

    def test_empty_index_returns_all_assets(self) -> None:
        chunk = _text_chunk(text="See Table 2-1.")
        table = EmbeddedTable(
            page=1,
            section=None,
            bbox=(0.0, 0.0, 10.0, 10.0),
            sort_key=0.0,
            summary="x",
            png_bytes=b"x",
            width=1,
            height=1,
        )

        orphan_figures, orphan_tables = attach_by_explicit_refs([chunk], [], [table])

        assert orphan_tables == [table]
        assert chunk.attached_assets == []


class TestExtractFigureRefsTableCases:
    def test_extracts_multiple_table_reference_styles(self) -> None:
        text = (
            "See Table 2-1 below. "
            "见表 3-4 所示。 "
            "Refer to table 5-6 for limits."
        )
        refs = extract_figure_refs(text)

        table_numbers = [ref.figure_number for ref in refs if ref.kind == "table"]
        assert set(table_numbers) == {"2-1", "3-4", "5-6"}
