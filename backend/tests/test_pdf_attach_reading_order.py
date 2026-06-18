import unittest
from types import SimpleNamespace

from app.services.pdf_attach_reading_order import pick_preceding_chunk


def _chunk(
    *,
    chunk_index: int,
    page: int,
    text: str = "正文",
    section: str | None = "第一章",
    sort_key: float | None = None,
    layout_y1: float | None = None,
) -> SimpleNamespace:
    layout_bbox = None
    if sort_key is not None and layout_y1 is not None:
        layout_bbox = (0.0, sort_key, 100.0, layout_y1)
    return SimpleNamespace(
        chunk_index=chunk_index,
        page=page,
        text=text,
        section=section,
        sort_key=sort_key,
        layout_y1=layout_y1,
        layout_bbox=layout_bbox,
        attached_assets=[],
    )


class PickPrecedingChunkTests(unittest.TestCase):
    def test_same_page_prefers_text_directly_above_asset(self) -> None:
        chunks = [
            _chunk(chunk_index=0, page=25, text="章节开头", sort_key=40.0, layout_y1=80.0),
            _chunk(chunk_index=1, page=25, text="电弧跟踪说明", sort_key=120.0, layout_y1=180.0),
            _chunk(chunk_index=2, page=25, text="图后说明", sort_key=420.0, layout_y1=460.0),
        ]

        target = pick_preceding_chunk(
            chunks,
            page=25,
            section="第一章",
            asset_bbox=(0.0, 400.0, 100.0, 500.0),
            asset_sort_key=400.0,
        )

        self.assertIs(target, chunks[1])

    def test_same_page_does_not_pick_text_below_asset(self) -> None:
        chunks = [
            _chunk(chunk_index=0, page=25, text="图前说明", sort_key=120.0, layout_y1=180.0),
            _chunk(chunk_index=1, page=25, text="图后说明", sort_key=420.0, layout_y1=460.0),
        ]

        target = pick_preceding_chunk(
            chunks,
            page=25,
            section="第一章",
            asset_bbox=(0.0, 400.0, 100.0, 500.0),
            asset_sort_key=400.0,
        )

        self.assertIs(target, chunks[0])

    def test_cross_page_falls_back_to_latest_earlier_page(self) -> None:
        chunks = [
            _chunk(chunk_index=0, page=23, text="较早说明", sort_key=100.0, layout_y1=150.0),
            _chunk(chunk_index=1, page=24, text="上一页说明", sort_key=80.0, layout_y1=120.0),
        ]

        target = pick_preceding_chunk(
            chunks,
            page=25,
            section="第一章",
            asset_bbox=(0.0, 200.0, 100.0, 300.0),
            asset_sort_key=200.0,
        )

        self.assertIs(target, chunks[1])

    def test_same_page_without_text_above_returns_none(self) -> None:
        chunks = [
            _chunk(chunk_index=0, page=25, text="图后说明", sort_key=420.0, layout_y1=460.0),
        ]

        target = pick_preceding_chunk(
            chunks,
            page=25,
            section="第一章",
            asset_bbox=(0.0, 400.0, 100.0, 500.0),
            asset_sort_key=400.0,
        )

        self.assertIsNone(target)

    def test_without_spatial_bounds_keeps_latest_chunk_fallback(self) -> None:
        chunks = [
            _chunk(chunk_index=0, page=24, text="A"),
            _chunk(chunk_index=1, page=25, text="B"),
        ]

        target = pick_preceding_chunk(
            chunks,
            page=25,
            section="第一章",
        )

        self.assertIs(target, chunks[1])


if __name__ == "__main__":
    unittest.main()
