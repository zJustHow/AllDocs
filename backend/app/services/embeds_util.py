"""Resolve visual embed markers in assistant answers."""

from __future__ import annotations

import re

from app.services.asset_urls import asset_url

EMBED_MARKER = re.compile(r"\{\{embed:(\d+)\}\}")


def embed_render_url(document_id: str, page: int) -> str:
    return f"/api/v1/documents/{document_id}/pages/{page}/render"


def _embed_for_chunk(chunk: dict) -> dict | None:
    page = chunk.get("page")
    document_id = chunk.get("document_id")
    if not page or not document_id:
        return None

    assets = chunk.get("assets") or []
    chunk_type = chunk.get("chunk_type") or "text"
    embed_type = "table" if chunk_type == "table" else "page"

    if assets:
        asset = assets[0]
        caption = asset.get("caption") or chunk.get("caption") or chunk.get("section")
        return {
            "document_id": str(document_id),
            "document_name": chunk.get("document_name"),
            "page": int(page),
            "type": asset.get("type") or embed_type,
            "url": asset.get("url") or asset_url(asset["asset_id"]),
            "asset_id": asset.get("asset_id"),
            "caption": caption,
        }

    return {
        "document_id": str(document_id),
        "document_name": chunk.get("document_name"),
        "page": int(page),
        "type": embed_type,
        "url": embed_render_url(str(document_id), int(page)),
        "asset_id": None,
        "caption": chunk.get("caption") or chunk.get("section"),
    }


def resolve_answer_embeds(answer: str, evidence: list[dict]) -> tuple[str, list[dict]]:
    embeds: list[dict] = []
    seen_refs: set[int] = set()

    for match in EMBED_MARKER.finditer(answer):
        ref = int(match.group(1))
        if ref in seen_refs:
            continue
        index = ref - 1
        if index < 0 or index >= len(evidence):
            continue

        payload = _embed_for_chunk(evidence[index])
        if payload is None:
            continue

        seen_refs.add(ref)
        embeds.append({"ref": ref, **payload})

    return answer, embeds


def public_embeds(embeds: list[dict]) -> list[dict]:
    return [
        {
            "ref": item["ref"],
            "document_id": item["document_id"],
            "document_name": item.get("document_name"),
            "page": item["page"],
            "type": item.get("type", "page"),
            "url": item["url"],
            "asset_id": item.get("asset_id"),
            "caption": item.get("caption"),
        }
        for item in embeds
    ]
