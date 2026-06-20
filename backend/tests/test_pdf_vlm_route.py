from unittest.mock import MagicMock, patch

from app.config import Settings
from app.services.caption import AssetVisionResult
from app.services.pdf_embedded_images import EmbeddedFigure
from app.services.pdf_tables import EmbeddedTable
from app.services.pdf_vlm_route import (
    _figure_to_raster_table,
    _looks_like_table_caption,
    _route_single_figure,
    route_figures_via_vlm,
)
from app.services.table_ocr import TableOCRResult


def _figure(
    *,
    page: int = 1,
    caption_text: str | None = None,
    figure_number: str | None = None,
    sort_key: float = 100.0,
    png_bytes: bytes = b"figure-png",
) -> EmbeddedFigure:
    return EmbeddedFigure(
        page=page,
        section="S1",
        bbox=(10.0, sort_key, 200.0, sort_key + 120.0),
        sort_key=sort_key,
        text="",
        png_bytes=png_bytes,
        width=120,
        height=90,
        figure_number=figure_number,
        caption_text=caption_text,
    )


def _table_ocr_result(*, summary: str = "| A | B |\n| 1 | 2 |") -> TableOCRResult:
    return TableOCRResult(
        summary=summary,
        row_count=3,
        col_count=2,
        filled_cells=6,
        score=0.9,
    )


class TestTableCaptionHeuristic:
    def test_recognizes_chinese_table_caption(self) -> None:
        assert _looks_like_table_caption("表 3-1 主要参数")

    def test_rejects_figure_caption_and_empty(self) -> None:
        assert not _looks_like_table_caption("图 3-1 系统框图")
        assert not _looks_like_table_caption(None)


class TestFigureToRasterTable:
    def test_preserves_metadata_and_summary(self) -> None:
        figure = _figure(caption_text="表 2-1 参数", figure_number="2-1")
        table = _figure_to_raster_table(
            figure,
            "| 型号 | 电压 |",
            vlm_caption="栅格表格",
        )

        assert isinstance(table, EmbeddedTable)
        assert table.page == figure.page
        assert table.bbox == figure.bbox
        assert table.summary == "| 型号 | 电压 |"
        assert table.figure_number == "2-1"
        assert table.caption_text == "表 2-1 参数"
        assert table.vlm_caption == "栅格表格"
        assert table.png_bytes == figure.png_bytes


class TestRouteSingleFigure:
    def test_classifies_figure_and_adds_vlm_caption(self) -> None:
        figure = _figure()
        caption_service = MagicMock()
        caption_service.classify_and_describe.return_value = AssetVisionResult(
            kind="figure",
            caption="接线示意图",
        )
        table_ocr = MagicMock()

        routed_figure, routed_table = _route_single_figure(
            figure,
            caption_service=caption_service,
            table_ocr=table_ocr,
            settings=Settings(),
        )

        assert routed_table is None
        assert routed_figure is not None
        assert routed_figure.vlm_caption == "接线示意图"
        table_ocr.recognize_image_bytes.assert_not_called()

    def test_promotes_vlm_table_when_ocr_succeeds(self) -> None:
        figure = _figure()
        caption_service = MagicMock()
        caption_service.classify_and_describe.return_value = AssetVisionResult(
            kind="table",
            caption="参数表",
        )
        table_ocr = MagicMock()
        table_ocr.recognize_image_bytes.return_value = _table_ocr_result()

        routed_figure, routed_table = _route_single_figure(
            figure,
            caption_service=caption_service,
            table_ocr=table_ocr,
            settings=Settings(),
        )

        assert routed_figure is None
        assert routed_table is not None
        assert routed_table.summary.startswith("| A | B |")
        assert routed_table.vlm_caption == "参数表"

    def test_table_caption_skips_vlm_and_promotes_via_ocr(self) -> None:
        figure = _figure(caption_text="表 2-1 额定参数")
        caption_service = MagicMock()
        table_ocr = MagicMock()
        table_ocr.recognize_image_bytes.return_value = _table_ocr_result(
            summary="| 型号 | 电压 |"
        )

        routed_figure, routed_table = _route_single_figure(
            figure,
            caption_service=caption_service,
            table_ocr=table_ocr,
            settings=Settings(),
        )

        caption_service.classify_and_describe.assert_not_called()
        assert routed_figure is None
        assert routed_table is not None
        assert routed_table.summary == "| 型号 | 电压 |"

    def test_keeps_figure_when_table_ocr_fails(self) -> None:
        figure = _figure()
        caption_service = MagicMock()
        caption_service.classify_and_describe.return_value = AssetVisionResult(
            kind="table",
            caption="疑似表格",
        )
        table_ocr = MagicMock()
        table_ocr.recognize_image_bytes.return_value = None

        routed_figure, routed_table = _route_single_figure(
            figure,
            caption_service=caption_service,
            table_ocr=table_ocr,
            settings=Settings(),
        )

        assert routed_table is None
        assert routed_figure is not None
        assert routed_figure.vlm_caption == "疑似表格"

    def test_returns_original_figure_when_vlm_unavailable(self) -> None:
        figure = _figure()
        caption_service = MagicMock()
        caption_service.classify_and_describe.return_value = None
        table_ocr = MagicMock()

        routed_figure, routed_table = _route_single_figure(
            figure,
            caption_service=caption_service,
            table_ocr=table_ocr,
            settings=Settings(),
        )

        assert routed_table is None
        assert routed_figure is figure


class TestRouteFiguresViaVlm:
    def test_returns_figures_unchanged_when_disabled(self) -> None:
        figures = [_figure(page=1), _figure(page=2, sort_key=200.0)]
        settings = Settings(ingest_caption_enabled=False)

        remaining, promoted = route_figures_via_vlm(
            figures,
            settings=settings,
            caption_service=MagicMock(),
        )

        assert remaining == figures
        assert promoted == []

    def test_returns_figures_unchanged_without_caption_service(self) -> None:
        figures = [_figure()]
        settings = Settings(ingest_caption_enabled=True)

        remaining, promoted = route_figures_via_vlm(
            figures,
            settings=settings,
            caption_service=None,
        )

        assert remaining == figures
        assert promoted == []

    def test_promotes_and_keeps_figures_on_same_page(self) -> None:
        figures = [
            _figure(sort_key=100.0),
            _figure(sort_key=250.0),
        ]
        caption_service = MagicMock()
        caption_service.classify_and_describe.side_effect = [
            AssetVisionResult(kind="table", caption="表一"),
            AssetVisionResult(kind="figure", caption="图二"),
        ]
        settings = Settings(ingest_caption_enabled=True, ingest_caption_max_per_page=2)

        with patch(
            "app.services.pdf_vlm_route.TableOCRService",
        ) as ocr_cls:
            ocr_cls.return_value.recognize_image_bytes.return_value = _table_ocr_result()
            remaining, promoted = route_figures_via_vlm(
                figures,
                settings=settings,
                caption_service=caption_service,
            )

        assert len(promoted) == 1
        assert promoted[0].vlm_caption == "表一"
        assert len(remaining) == 1
        assert remaining[0].vlm_caption == "图二"

    def test_respects_max_per_page_limit(self) -> None:
        figures = [
            _figure(sort_key=100.0),
            _figure(sort_key=200.0),
            _figure(sort_key=300.0),
        ]
        caption_service = MagicMock()
        caption_service.classify_and_describe.return_value = AssetVisionResult(
            kind="figure",
            caption="图",
        )
        settings = Settings(ingest_caption_enabled=True, ingest_caption_max_per_page=1)

        remaining, promoted = route_figures_via_vlm(
            figures,
            settings=settings,
            caption_service=caption_service,
        )

        assert len(remaining) == 3
        assert promoted == []
        assert remaining[0].vlm_caption == "图"
        assert remaining[1].vlm_caption is None
        assert remaining[2].vlm_caption is None

    def test_continues_when_single_figure_route_raises(self) -> None:
        figures = [_figure(sort_key=100.0), _figure(sort_key=200.0)]
        caption_service = MagicMock()
        caption_service.classify_and_describe.side_effect = [
            RuntimeError("vlm down"),
            AssetVisionResult(kind="figure", caption="备用图"),
        ]
        settings = Settings(ingest_caption_enabled=True)

        remaining, promoted = route_figures_via_vlm(
            figures,
            settings=settings,
            caption_service=caption_service,
        )

        assert promoted == []
        assert len(remaining) == 2
        assert remaining[0].vlm_caption is None
        assert remaining[1].vlm_caption == "备用图"
