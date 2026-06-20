import fitz

from app.config import Settings
from app.services.pdf_image_stitch import stitch_png_bytes_vertically
from app.services.pdf_table_merge import merge_cross_page_tables
from app.services.pdf_tables import EmbeddedTable


def _solid_png(*, width: int, height: int, color: tuple[float, float, float]) -> bytes:
    document = fitz.open()
    try:
        page = document.new_page(width=width, height=height)
        page.draw_rect(page.rect, color=color, fill=color)
        return page.get_pixmap(alpha=False).tobytes("png")
    finally:
        document.close()


class TestStitchPngBytesVertically:
    def test_single_image_passthrough(self) -> None:
        png = _solid_png(width=80, height=40, color=(1, 0, 0))
        stitched, width, height = stitch_png_bytes_vertically([png])
        assert stitched == png
        assert width == 80
        assert height == 40

    def test_stacks_images_with_gap(self) -> None:
        top = _solid_png(width=100, height=30, color=(1, 0, 0))
        bottom = _solid_png(width=80, height=50, color=(0, 0, 1))
        stitched, width, height = stitch_png_bytes_vertically([top, bottom], gap=4)
        assert width == 100
        assert height == 30 + 4 + 50

        pixmap = fitz.Pixmap(stitched)
        assert pixmap.width == 100
        assert pixmap.height == 84


class TestCrossPageMergeStitchedPng:
    def test_merged_table_uses_stitched_png(self) -> None:
        top_png = _solid_png(width=120, height=40, color=(1, 0, 0))
        bottom_png = _solid_png(width=120, height=60, color=(0, 0, 1))
        left = EmbeddedTable(
            page=1,
            section="S1",
            bbox=(10.0, 620.0, 500.0, 760.0),
            sort_key=620.0,
            summary="| 型号 | 电压 |\n| --- | --- |\n| A1 | 220V |",
            png_bytes=top_png,
            width=120,
            height=40,
        )
        right = EmbeddedTable(
            page=2,
            section="S1",
            bbox=(10.0, 40.0, 500.0, 180.0),
            sort_key=40.0,
            summary="| 型号 | 电压 |\n| --- | --- |\n| A2 | 110V |",
            png_bytes=bottom_png,
            width=120,
            height=60,
        )
        settings = Settings()
        merged = merge_cross_page_tables(
            [left, right],
            page_heights={1: 800.0, 2: 800.0},
            settings=settings,
        )
        assert len(merged) == 1
        table = merged[0]
        assert table.width == 120
        assert table.height == 40 + settings.pdf_cross_page_table_stitch_gap + 60
        assert table.png_bytes != top_png
        assert table.png_bytes != bottom_png

    def test_stitch_disabled_keeps_first_page_png(self) -> None:
        top_png = _solid_png(width=120, height=40, color=(1, 0, 0))
        bottom_png = _solid_png(width=120, height=60, color=(0, 0, 1))
        left = EmbeddedTable(
            page=1,
            section="S1",
            bbox=(10.0, 620.0, 500.0, 760.0),
            sort_key=620.0,
            summary="| 型号 | 电压 |\n| --- | --- |\n| A1 | 220V |",
            png_bytes=top_png,
            width=120,
            height=40,
        )
        right = EmbeddedTable(
            page=2,
            section="S1",
            bbox=(10.0, 40.0, 500.0, 180.0),
            sort_key=40.0,
            summary="| 型号 | 电压 |\n| --- | --- |\n| A2 | 110V |",
            png_bytes=bottom_png,
            width=120,
            height=60,
        )
        settings = Settings(pdf_stitch_cross_page_table_png=False)
        merged = merge_cross_page_tables(
            [left, right],
            page_heights={1: 800.0, 2: 800.0},
            settings=settings,
        )
        assert merged[0].png_bytes == top_png
        assert merged[0].width == 120
        assert merged[0].height == 40
