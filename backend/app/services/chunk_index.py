"""Helpers for indexing and displaying chunk text vs visual captions."""

from __future__ import annotations

from typing import Protocol

_VISUAL_ASSET_TYPES = frozenset({"table", "figure"})


class _VisualAsset(Protocol):
    asset_type: str
    caption: str | None


def format_asset_caption_line(asset_type: str, caption: str) -> str:
    label = "表格" if asset_type == "table" else "图示"
    return f"[{label}] {caption.strip()}"


def merge_visual_descriptions_into_text(
    text: str,
    *,
    chunk_caption: str | None = None,
    assets: list[_VisualAsset] | None = None,
    replace_short_body: bool = False,
    min_body_chars: int = 50,
) -> str:
    """Append VLM descriptions to mounted text, or use them as the chunk body when empty."""
    body = text.strip()
    parts: list[str] = []
    seen: set[str] = set()

    for asset in assets or []:
        if asset.asset_type not in _VISUAL_ASSET_TYPES:
            continue
        caption = (asset.caption or "").strip()
        if not caption:
            continue
        line = format_asset_caption_line(asset.asset_type, caption)
        if line not in seen:
            seen.add(line)
            parts.append(line)

    chunk_line = (chunk_caption or "").strip()
    if chunk_line and chunk_line not in seen:
        parts.append(chunk_line)

    if not parts:
        return text
    if not body:
        return "\n\n".join(parts)
    if replace_short_body and len(body) < min_body_chars:
        return "\n\n".join(parts)
    return f"{body}\n\n" + "\n\n".join(parts)


def captions_merged_into_text(
    text: str,
    *,
    chunk_caption: str | None = None,
    asset_captions: list[str] | None = None,
) -> bool:
    """True when separate caption fields are already reflected in chunk.text."""
    if chunk_caption and chunk_caption.strip() and chunk_caption.strip() not in text:
        return False
    for caption in asset_captions or []:
        if caption and caption.strip() and caption.strip() not in text:
            return False
    return bool((chunk_caption and chunk_caption.strip()) or asset_captions)


def merge_captions(
    chunk_caption: str | None,
    asset_captions: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if chunk_caption and chunk_caption.strip():
        parts.append(chunk_caption.strip())
    for caption in asset_captions or []:
        if caption and caption.strip() and caption.strip() not in parts:
            parts.append(caption.strip())
    return "\n".join(parts)


def chunk_embedding_text(
    text: str,
    section: str | None,
    *,
    caption: str | None = None,
    asset_captions: list[str] | None = None,
) -> str:
    parts: list[str] = []
    if section:
        parts.append(section)
    body = text.strip()
    if body:
        parts.append(body)
    visual = merge_captions(caption, asset_captions)
    if visual:
        parts.append(f"[visual] {visual}")
    return "\n".join(parts) if parts else text


def chunk_rerank_text(
    text: str,
    *,
    caption: str | None = None,
    asset_captions: list[str] | None = None,
) -> str:
    visual = merge_captions(caption, asset_captions)
    if not visual:
        return text
    if not text.strip():
        return visual
    return f"{text.strip()}\n\n[visual] {visual}"


def chunk_fulltext_caption(
    caption: str | None,
    asset_captions: list[str] | None = None,
) -> str:
    return merge_captions(caption, asset_captions)


def chunk_display_snippet(
    text: str,
    *,
    caption: str | None = None,
    asset_captions: list[str] | None = None,
    limit: int = 300,
) -> str:
    visual = merge_captions(caption, asset_captions)
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
    asset_captions: list[str] | None = None,
) -> str:
    visual = merge_captions(caption, asset_captions)
    parts: list[str] = []
    if text.strip():
        parts.append(text.strip())
    if visual:
        parts.append(f"[图像描述] {visual}")
    return "\n".join(parts) if parts else text
