"""Helpers for indexing and displaying chunk text vs visual captions."""

from __future__ import annotations

from typing import Any


def _read_asset_field(asset: object, field: str) -> str | None:
    if isinstance(asset, dict):
        value = asset.get(field)
    else:
        value = getattr(asset, field, None)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _append_unique_caption(parts: list[str], value: str | None) -> None:
    if value and value not in parts:
        parts.append(value)


def asset_caption_kwargs(
    chunk_caption: str | None,
    assets: list,
) -> dict[str, Any]:
    """Collect chunk- and asset-level caption fields for indexing helpers."""
    return {
        "caption": chunk_caption,
        "asset_figure_captions": [
            value
            for asset in assets
            if (value := _read_asset_field(asset, "figure_caption"))
        ],
        "asset_captions": [
            value for asset in assets if (value := _read_asset_field(asset, "caption"))
        ],
        "asset_vlm_captions": [
            value
            for asset in assets
            if (value := _read_asset_field(asset, "vlm_caption"))
        ],
    }


def _merged_visual(
    *,
    caption: str | None = None,
    asset_figure_captions: list[str] | None = None,
    asset_captions: list[str] | None = None,
    asset_vlm_captions: list[str] | None = None,
) -> str:
    parts: list[str] = []
    _append_unique_caption(parts, caption.strip() if caption and caption.strip() else None)
    for group in (asset_figure_captions, asset_captions, asset_vlm_captions):
        for value in group or []:
            _append_unique_caption(parts, value.strip() if value and value.strip() else None)
    return "\n".join(parts)


def captions_merged_into_text(
    text: str,
    *,
    caption: str | None = None,
    asset_figure_captions: list[str] | None = None,
    asset_captions: list[str] | None = None,
    asset_vlm_captions: list[str] | None = None,
) -> bool:
    """True when separate caption fields are already reflected in chunk.text."""
    for value in (caption,):
        if value and value.strip() and value.strip() not in text:
            return False
    for group in (asset_figure_captions, asset_captions, asset_vlm_captions):
        for value in group or []:
            if value and value.strip() and value.strip() not in text:
                return False
    return bool(
        (caption and caption.strip())
        or asset_figure_captions
        or asset_captions
        or asset_vlm_captions
    )


def merge_captions(
    *,
    caption: str | None = None,
    asset_captions: list[str] | None = None,
    asset_figure_captions: list[str] | None = None,
    asset_vlm_captions: list[str] | None = None,
) -> str:
    return _merged_visual(
        caption=caption,
        asset_figure_captions=asset_figure_captions,
        asset_captions=asset_captions,
        asset_vlm_captions=asset_vlm_captions,
    )


def chunk_embedding_text(
    text: str,
    section: str | None,
    *,
    caption: str | None = None,
    asset_figure_captions: list[str] | None = None,
    asset_captions: list[str] | None = None,
    asset_vlm_captions: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if section:
        parts.append(section)
    body = text.strip()
    if body:
        parts.append(body)
    visual = _merged_visual(
        caption=caption,
        asset_figure_captions=asset_figure_captions,
        asset_captions=asset_captions,
        asset_vlm_captions=asset_vlm_captions,
    )
    if visual:
        parts.append(f"[visual] {visual}")
    return "\n".join(parts) if parts else text


def chunk_rerank_text(
    text: str,
    *,
    caption: str | None = None,
    asset_figure_captions: list[str] | None = None,
    asset_captions: list[str] | None = None,
    asset_vlm_captions: list[str] | None = None,
) -> str:
    visual = _merged_visual(
        caption=caption,
        asset_figure_captions=asset_figure_captions,
        asset_captions=asset_captions,
        asset_vlm_captions=asset_vlm_captions,
    )
    if not visual:
        return text
    if not text.strip():
        return visual
    return f"{text.strip()}\n\n[visual] {visual}"


def chunk_display_snippet(
    text: str,
    *,
    caption: str | None = None,
    asset_figure_captions: list[str] | None = None,
    asset_captions: list[str] | None = None,
    asset_vlm_captions: list[str] | None = None,
    limit: int = 300,
) -> str:
    visual = _merged_visual(
        caption=caption,
        asset_figure_captions=asset_figure_captions,
        asset_captions=asset_captions,
        asset_vlm_captions=asset_vlm_captions,
    )
    if visual and not text.strip():
        return visual[:limit]
    if visual:
        combined = f"{text.strip()}\n[visual] {visual}"
        return combined[:limit]
    return text[:limit]


def format_context_body(
    text: str,
    *,
    caption: str | None = None,
    asset_figure_captions: list[str] | None = None,
    asset_captions: list[str] | None = None,
    asset_vlm_captions: list[str] | None = None,
) -> str:
    visual = _merged_visual(
        caption=caption,
        asset_figure_captions=asset_figure_captions,
        asset_captions=asset_captions,
        asset_vlm_captions=asset_vlm_captions,
    )
    parts: list[str] = []
    if text.strip():
        parts.append(text.strip())
    if visual:
        parts.append(f"[图像描述] {visual}")
    return "\n".join(parts) if parts else text
