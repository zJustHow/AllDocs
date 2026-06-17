"""Resolve visual embed markers in assistant answers."""

from __future__ import annotations

import re

from app.services.asset_urls import asset_url
from app.services.shared_contract import (
    citation_ref_pattern,
    embed_dedupe_key,
    embed_marker_pattern,
    format_embed_marker,
)
from app.services.visual_asset_util import VISUAL_ASSET_TYPES, primary_visual_asset

EMBED_MARKER = embed_marker_pattern()
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


def _paragraph_at_position(answer: str, pos: int) -> str:
    start = answer.rfind("\n\n", 0, pos)
    start = 0 if start < 0 else start + 2
    end = answer.find("\n\n", pos)
    end = len(answer) if end < 0 else end
    return answer[start:end]


def _best_citation_insert_at(answer: str, ref: int, chunk: dict) -> int | None:
    matches = list(citation_ref_pattern(ref).finditer(answer))
    if not matches:
        return None

    chunk_section = (chunk.get("section") or chunk.get("caption") or "").strip()
    if chunk_section:
        for match in reversed(matches):
            paragraph = _paragraph_at_position(answer, match.start())
            first_line = paragraph.split("\n", 1)[0].strip().lstrip("*").rstrip("*")
            if (
                chunk_section in paragraph
                or first_line in chunk_section
                or chunk_section in first_line
            ):
                return match.start()

    return matches[-1].start()


def embed_render_url(document_id: str, page: int) -> str:
    return f"/api/v1/documents/{document_id}/pages/{page}/render"


def _visual_asset_type(chunk: dict) -> str | None:
    asset = primary_visual_asset(chunk)
    if asset is None:
        return None
    asset_type = asset.get("type") or "figure"
    if asset_type in VISUAL_ASSET_TYPES:
        return asset_type
    return None


def _chunk_should_embed(chunk: dict) -> bool:
    """Chunks with a stored table/figure crop asset may appear in answers."""
    return primary_visual_asset(chunk) is not None


def _embed_display_caption(chunk: dict, asset: dict | None = None) -> str | None:
    """Prefer section titles over long VLM image descriptions."""
    for candidate in (chunk.get("section"), chunk.get("caption")):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    if asset:
        asset_caption = asset.get("caption")
        if asset_caption and str(asset_caption).strip():
            text = str(asset_caption).strip()
            if len(text) <= 100:
                return text
    return None


def _embed_for_chunk(chunk: dict) -> dict | None:
    visual_type = _visual_asset_type(chunk)
    if not visual_type:
        return None

    page = chunk.get("page")
    document_id = chunk.get("document_id")
    if not page or not document_id:
        return None

    asset = primary_visual_asset(chunk)
    if asset and asset.get("asset_id"):
        caption = _embed_display_caption(chunk, asset)
        asset_type = asset.get("type") or visual_type
        embed_type = "figure" if asset_type == "figure" else "table"
        return {
            "document_id": str(document_id),
            "document_name": chunk.get("document_name"),
            "page": int(page),
            "type": embed_type,
            "url": asset.get("url") or asset_url(asset["asset_id"]),
            "asset_id": asset.get("asset_id"),
            "bbox": asset.get("bbox"),
            "caption": caption,
        }

    return {
        "document_id": str(document_id),
        "document_name": chunk.get("document_name"),
        "page": int(page),
        "type": visual_type,
        "url": embed_render_url(str(document_id), int(page)),
        "asset_id": None,
        "bbox": None,
        "caption": _embed_display_caption(chunk),
    }


def _collapse_extra_blank_lines(text: str) -> str:
    return _EXTRA_BLANK_LINES.sub("\n\n", text).strip()


def evidence_has_visual(chunks: list[dict]) -> bool:
    return any(_chunk_should_embed(chunk) for chunk in chunks)


def auto_insert_embed_markers(answer: str, cited_chunks: list[dict]) -> str:
    """Insert {{embed:N}} for visual cited chunks when the model omitted markers."""
    existing_refs = {int(match) for match in EMBED_MARKER.findall(answer)}
    seen_keys: set[str] = set()
    for ref in existing_refs:
        index = ref - 1
        if index < 0 or index >= len(cited_chunks):
            continue
        payload = _embed_for_chunk(cited_chunks[index])
        if payload is not None:
            seen_keys.add(embed_dedupe_key(payload))

    inserts: list[tuple[int, str]] = []

    for ref, chunk in enumerate(cited_chunks, start=1):
        if ref in existing_refs or not _chunk_should_embed(chunk):
            continue
        payload = _embed_for_chunk(chunk)
        if payload is None:
            continue
        dedupe_key = embed_dedupe_key(payload)
        if dedupe_key in seen_keys:
            continue
        marker = format_embed_marker(ref)
        insert_at = _best_citation_insert_at(answer, ref, chunk)
        if insert_at is None:
            continue
        inserts.append((insert_at, f"\n\n{marker}\n\n"))
        seen_keys.add(dedupe_key)
        existing_refs.add(ref)

    for insert_at, marker in sorted(inserts, key=lambda item: item[0], reverse=True):
        answer = answer[:insert_at] + marker + answer[insert_at:]

    return answer


def renumber_embed_markers(answer: str, old_to_new: dict[int, int]) -> str:
    if not old_to_new:
        return answer

    def replace(match: re.Match[str]) -> str:
        old_ref = int(match.group(1))
        new_ref = old_to_new.get(old_ref)
        if new_ref is None:
            return match.group(0)
        return format_embed_marker(new_ref)

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
            return match.group(0)
        chunk = evidence[index]
        if not _chunk_should_embed(chunk):
            return ""
        payload = _embed_for_chunk(chunk)
        if payload is None:
            return ""
        payload_key = embed_dedupe_key(payload)
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
            "bbox": item.get("bbox"),
            "caption": item.get("caption"),
        }
        for item in embeds
    ]
