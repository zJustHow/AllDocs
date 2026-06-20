from app.services.embeds_util import _embed_display_caption, _embed_for_asset
from app.services.pdf_layout_regions import resolve_asset_regions


def test_resolve_asset_regions_prefers_layout_regions() -> None:
    asset = {
        "page": 1,
        "bbox": [0.0, 0.0, 100.0, 100.0],
        "layout_regions": [
            {"page": 1, "bbox": [10.0, 620.0, 500.0, 760.0]},
            {"page": 2, "bbox": [10.0, 40.0, 500.0, 180.0]},
        ],
    }
    regions = resolve_asset_regions(asset)
    assert len(regions) == 2
    assert regions[1]["page"] == 2


def test_embed_display_caption_truncates_long_figure_caption() -> None:
    long_caption = "图 4-7 " + ("电弧跟踪模式说明" * 20)
    caption = _embed_display_caption({}, {"figure_caption": long_caption})
    assert caption is not None
    assert len(caption) == 120
    assert caption.endswith("…")
    assert caption.startswith("图 4-7")


def test_embed_display_caption_keeps_short_figure_caption() -> None:
    caption = _embed_display_caption({}, {"figure_caption": "图 4-7 电弧跟踪模式设置"})
    assert caption == "图 4-7 电弧跟踪模式设置"


def test_embed_for_asset_uses_multi_region_layout() -> None:
    chunk = {
        "document_id": "doc-1",
        "document_name": "Spec",
        "page": 1,
        "section": "Chapter 1",
    }
    asset = {
        "asset_id": "asset-1",
        "type": "table",
        "page": 1,
        "bbox": [10.0, 620.0, 500.0, 760.0],
        "layout_regions": [
            {"page": 1, "bbox": [10.0, 620.0, 500.0, 760.0]},
            {"page": 2, "bbox": [10.0, 40.0, 500.0, 180.0]},
        ],
        "figure_number": "3-1",
    }
    embed = _embed_for_asset(chunk, asset, ref=1)
    assert embed is not None
    assert len(embed["regions"]) == 2
    assert embed["regions"][0]["page"] == 1
    assert embed["regions"][1]["page"] == 2
