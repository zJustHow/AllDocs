"""Helpers for serializing answer embed payloads."""

from __future__ import annotations

from app.services.asset_urls import asset_url
from app.services.shared_contract import embed_dedupe_key
from app.services.visual_asset_util import VISUAL_ASSET_TYPES, chunk_visual_assets


def _embed_display_caption(chunk: dict, asset: dict) -> str | None:
    figure_caption = str(asset.get("figure_caption") or "").strip()
    if figure_caption and len(figure_caption) <= 120:
        return figure_caption
    caption = str(asset.get("caption") or "").strip()
    if caption and len(caption) <= 120:
        return caption
    figure_number = str(asset.get("figure_number") or "").strip()
    if figure_number:
        prefix = "图" if (asset.get("type") or "figure") == "figure" else "表"
        return f"{prefix} {figure_number}"
    for candidate in (chunk.get("section"), chunk.get("caption")):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return None


def _embed_for_asset(chunk: dict, asset: dict, *, ref: int) -> dict | None:
    document_id = chunk.get("document_id")
    asset_id = asset.get("asset_id")
    if not document_id or not asset_id:
        return None

    asset_type = asset.get("type") or "figure"
    if asset_type not in VISUAL_ASSET_TYPES:
        return None

    page = asset.get("page") or chunk.get("page")
    if page is None:
        return None

    embed_type = "figure" if asset_type == "figure" else "table"
    return {
        "ref": ref,
        "document_id": str(document_id),
        "document_name": chunk.get("document_name"),
        "page": int(page),
        "type": embed_type,
        "url": asset.get("url") or asset_url(str(asset_id)),
        "asset_id": str(asset_id),
        "content_hash": asset.get("content_hash"),
        "bbox": asset.get("bbox"),
        "caption": _embed_display_caption(chunk, asset),
        "figure_caption": asset.get("figure_caption"),
        "figure_number": asset.get("figure_number"),
    }


def build_citation_embeds(cited_chunks: list[dict]) -> list[dict]:
    """Attach visual assets from cited chunks to their [n] reference."""
    embeds: list[dict] = []
    seen_keys: set[str] = set()
    for ref, chunk in enumerate(cited_chunks, start=1):
        for asset in chunk_visual_assets(chunk):
            payload = _embed_for_asset(chunk, asset, ref=ref)
            if payload is None:
                continue
            dedupe_key = embed_dedupe_key(payload)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            embeds.append(payload)
    return embeds


def public_embeds(embeds: list[dict]) -> list[dict]:
    return [
        {
            "ref": item["ref"],
            "block_index": item.get("block_index"),
            "document_id": item["document_id"],
            "document_name": item.get("document_name"),
            "page": item["page"],
            "type": item.get("type", "page"),
            "url": item["url"],
            "asset_id": item.get("asset_id"),
            "content_hash": item.get("content_hash"),
            "bbox": item.get("bbox"),
            "caption": item.get("caption"),
            "figure_caption": item.get("figure_caption"),
            "figure_number": item.get("figure_number"),
        }
        for item in embeds
    ]
