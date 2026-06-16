"""Resolve visual embed markers in assistant answers."""

from __future__ import annotations

import re

from app.services.asset_urls import asset_url

EMBED_MARKER = re.compile(r"\{\{embed:(\d+)\}\}")
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


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
        asset_type = asset.get("type") or embed_type
        if asset_type == "figure":
            embed_type = "figure"
        elif chunk_type == "table":
            embed_type = "table"
        else:
            embed_type = asset_type
        return {
            "document_id": str(document_id),
            "document_name": chunk.get("document_name"),
            "page": int(page),
            "type": embed_type,
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


def _embed_dedupe_key(payload: dict) -> str:
    asset_id = payload.get("asset_id")
    if asset_id:
        return f"asset:{asset_id}"
    return f"page:{payload['document_id']}:{payload['page']}"


def _collapse_extra_blank_lines(text: str) -> str:
    return _EXTRA_BLANK_LINES.sub("\n\n", text).strip()


def renumber_embed_markers(answer: str, old_to_new: dict[int, int]) -> str:
    if not old_to_new:
        return answer

    def replace(match: re.Match[str]) -> str:
        old_ref = int(match.group(1))
        new_ref = old_to_new.get(old_ref)
        if new_ref is None:
            return match.group(0)
        return f"{{{{embed:{new_ref}}}}}"

    return EMBED_MARKER.sub(replace, answer)


def dedupe_answer_embed_markers(
    answer: str,
    evidence: list[dict],
) -> tuple[str, list[dict]]:
    """Resolve agent-placed {{embed:N}} markers; each image appears at most once."""
    embeds: list[dict] = []
    seen_payload_keys: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        ref = int(match.group(1))
        index = ref - 1
        if index < 0 or index >= len(evidence):
            return ""
        payload = _embed_for_chunk(evidence[index])
        if payload is None:
            return ""
        payload_key = _embed_dedupe_key(payload)
        if payload_key in seen_payload_keys:
            return ""
        seen_payload_keys.add(payload_key)
        embeds.append({"ref": ref, **payload})
        return match.group(0)

    answer = EMBED_MARKER.sub(replace, answer)
    return _collapse_extra_blank_lines(answer), embeds


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
