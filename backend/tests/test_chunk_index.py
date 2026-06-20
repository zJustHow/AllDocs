from app.services.chunk_index import (
    asset_caption_kwargs,
    captions_merged_into_text,
    chunk_display_snippet,
    chunk_embedding_text,
    chunk_rerank_text,
    format_context_body,
    merge_captions,
)


def test_asset_caption_kwargs_collects_asset_fields() -> None:
    kwargs = asset_caption_kwargs(
        "章节说明",
        [
            {"figure_caption": "图1-1", "caption": "示意图", "vlm_caption": "设备外观"},
        ],
    )

    assert kwargs["caption"] == "章节说明"
    assert kwargs["asset_figure_captions"] == ["图1-1"]
    assert kwargs["asset_vlm_captions"] == ["设备外观"]


def test_captions_merged_into_text_detects_missing_caption_in_body() -> None:
    assert captions_merged_into_text(
        "正文",
        caption="未写入正文的图注",
    ) is False


def test_chunk_embedding_text_appends_visual_block() -> None:
    text = chunk_embedding_text(
        "正文",
        "第一章",
        caption="图注",
        asset_figure_captions=["图1-1"],
    )

    assert "第一章" in text
    assert "正文" in text
    assert "[visual]" in text
    assert "图1-1" in text


def test_chunk_rerank_text_uses_visual_only_when_body_empty() -> None:
    assert chunk_rerank_text(
        "",
        asset_figure_captions=["图2-3"],
    ) == "图2-3"


def test_chunk_display_snippet_prefers_visual_when_text_empty() -> None:
    snippet = chunk_display_snippet("", asset_vlm_captions=["VLM 描述"], limit=20)
    assert snippet == "VLM 描述"


def test_format_context_body_adds_image_description_block() -> None:
    body = format_context_body("步骤一", asset_figure_captions=["图3-1"])
    assert "步骤一" in body
    assert "[图像描述]" in body
    assert "图3-1" in body


def test_merge_captions_deduplicates_values() -> None:
    merged = merge_captions(
        caption="图注",
        asset_figure_captions=["图注", "图1-2"],
        asset_captions=["补充说明"],
    )
    assert merged == "图注\n图1-2\n补充说明"
