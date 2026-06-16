"""Resolve visual embed markers in assistant answers."""

from __future__ import annotations

import re

from app.services.asset_urls import asset_url
from app.services.citations_util import INLINE_CITATION_REF

EMBED_MARKER = re.compile(r"\{\{embed:(\d+)\}\}")
FIGURE_TEXT_HINT = re.compile(r"图\s*[\d\-]+|如图|Figure\s*\d", re.IGNORECASE)
_VISUAL_CHUNK_TYPES = frozenset({"table", "figure", "procedure", "warning"})
_MAX_AUTO_CITATION_EMBEDS = 4


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


def _chunk_visual_text(chunk: dict) -> str:
    return " ".join(
        part
        for part in (
            chunk.get("text"),
            chunk.get("snippet"),
            chunk.get("caption"),
            chunk.get("section"),
        )
        if isinstance(part, str) and part.strip()
    )


def _should_auto_embed(chunk: dict) -> bool:
    if chunk.get("assets"):
        return True
    chunk_type = chunk.get("chunk_type") or "text"
    if chunk_type in _VISUAL_CHUNK_TYPES:
        return True
    if chunk.get("caption"):
        return True
    return bool(FIGURE_TEXT_HINT.search(_chunk_visual_text(chunk)))


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


def _inject_citation_embed_markers(answer: str, refs: set[int]) -> str:
    if not refs:
        return answer

    matches = list(INLINE_CITATION_REF.finditer(answer))
    for match in reversed(matches):
        ref = int(match.group(1) or match.group(2))
        if ref not in refs:
            continue
        marker = f"{{{{embed:{ref}}}}}"
        start = match.start()
        if marker in answer[max(0, start - len(marker) - 4) : start]:
            continue
        answer = answer[:start] + marker + "\n\n" + answer[start:]
    return answer


def resolve_citation_embeds(
    answer: str,
    cited_chunks: list[dict],
    *,
    existing_embeds: list[dict] | None = None,
    max_auto_embeds: int = _MAX_AUTO_CITATION_EMBEDS,
) -> tuple[str, list[dict]]:
    """Add embeds for visual cited chunks; inject {{embed:n}} markers."""
    embeds = list(existing_embeds or [])
    seen_refs = {item["ref"] for item in embeds}
    seen_payload_keys = {_embed_dedupe_key(item) for item in embeds}
    citation_refs: set[int] = set()
    auto_embed_count = 0

    for match in INLINE_CITATION_REF.finditer(answer):
        ref = int(match.group(1) or match.group(2))
        if ref in seen_refs or ref in citation_refs:
            continue
        if ref < 1 or ref > len(cited_chunks):
            continue
        chunk = cited_chunks[ref - 1]
        if not _should_auto_embed(chunk):
            continue
        payload = _embed_for_chunk(chunk)
        if payload is None:
            continue
        payload_key = _embed_dedupe_key(payload)
        if payload_key in seen_payload_keys:
            continue
        if auto_embed_count >= max_auto_embeds:
            continue
        embeds.append({"ref": ref, **payload})
        seen_refs.add(ref)
        seen_payload_keys.add(payload_key)
        citation_refs.add(ref)
        auto_embed_count += 1

    answer = _inject_citation_embed_markers(answer, citation_refs)
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
