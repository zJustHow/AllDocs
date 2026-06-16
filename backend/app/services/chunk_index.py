"""Helpers for indexing and displaying chunk text vs visual captions."""

from __future__ import annotations


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
