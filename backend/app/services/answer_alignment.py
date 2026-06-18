"""Split synthesized answers into blocks and align them to chunk sub indexes."""

from __future__ import annotations

import math
import re
from typing import Any

from app.config import Settings, get_settings
from app.services.asset_urls import asset_url
from app.services.chunk_alignment import build_chunk_sub_index
from app.services.embedding_provider import get_embedding_service
from app.services.shared_contract import (
    embed_dedupe_key,
    inline_citation_ref_pattern,
    strip_inline_markers,
)
from app.services.visual_asset_util import VISUAL_ASSET_TYPES, chunk_visual_assets

_BLOCK_SPLIT = re.compile(
    r"(?=\n\s*(?:\d+[.)、．]|[\u2022●○▪•·\-–—]\s|\*\s+))"
)
_INLINE_CITATION = inline_citation_ref_pattern()


def _extract_citation_refs(raw_text: str) -> list[int]:
    refs: list[int] = []
    seen: set[int] = set()
    for match in _INLINE_CITATION.finditer(raw_text):
        ref = int(match.group(1) or match.group(2))
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def split_answer_blocks(answer: str) -> list[dict[str, Any]]:
    """Split answer into prose blocks; collect inline [n] refs anywhere in each block."""
    answer = answer.strip()
    if not answer:
        return []

    parts = [part.strip() for part in _BLOCK_SPLIT.split(answer) if part.strip()]
    if len(parts) <= 1:
        parts = [part.strip() for part in re.split(r"\n{2,}", answer) if part.strip()]
    if not parts:
        parts = [answer]

    blocks: list[dict[str, Any]] = []
    for raw_text in parts:
        blocks.append(
            {
                "block_index": len(blocks),
                "text": strip_inline_markers(raw_text),
                "raw_text": raw_text,
                "citation_refs": _extract_citation_refs(raw_text),
            }
        )
    return blocks


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _chunk_subs(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    stored = chunk.get("sub_index") or chunk.get("step_index")
    if stored:
        return stored
    return build_chunk_sub_index(
        chunk.get("text") or "",
        chunk.get("assets") or [],
    )


def _assets_by_id(chunk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(asset.get("asset_id")): asset
        for asset in chunk_visual_assets(chunk)
        if asset.get("asset_id")
    }


def _embed_display_caption(chunk: dict[str, Any], asset: dict[str, Any]) -> str | None:
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


def _embed_for_asset(
    chunk: dict[str, Any],
    asset: dict[str, Any],
    *,
    block_index: int,
    ref: int,
) -> dict[str, Any] | None:
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
        "block_index": block_index,
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


def _best_sub_for_block(
    block_text: str,
    subs: list[dict[str, Any]],
    vectors: dict[str, list[float]],
    *,
    threshold: float,
) -> dict[str, Any] | None:
    block_vector = vectors.get(block_text)
    if block_vector is None:
        return None

    best_sub: dict[str, Any] | None = None
    best_score = threshold
    for sub in subs:
        if not sub.get("asset_ids"):
            continue
        index_text = str(sub.get("index_text") or sub.get("text") or "").strip()
        if not index_text:
            continue
        sub_vector = vectors.get(index_text)
        if sub_vector is None:
            continue
        score = _cosine_similarity(block_vector, sub_vector)
        if score >= best_score:
            best_score = score
            best_sub = sub
    return best_sub


def build_aligned_embeds(
    answer: str,
    cited_chunks: list[dict[str, Any]],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return embeds aligned to answer blocks via sub similarity."""
    settings = settings or get_settings()
    blocks = split_answer_blocks(answer)
    if not blocks or not cited_chunks:
        return []

    alignments: list[tuple[dict[str, Any], int, dict[str, Any], list[dict[str, Any]]]] = []
    texts_to_embed: list[str] = []

    for block in blocks:
        block_text = str(block.get("text") or "").strip()
        if not block_text:
            continue
        citation_refs = block.get("citation_refs") or []
        if not citation_refs:
            continue
        texts_to_embed.append(block_text)

        for ref in citation_refs:
            if ref < 1 or ref > len(cited_chunks):
                continue
            chunk = cited_chunks[ref - 1]
            subs = _chunk_subs(chunk)
            if not subs:
                continue
            for sub in subs:
                index_text = str(sub.get("index_text") or sub.get("text") or "").strip()
                if index_text:
                    texts_to_embed.append(index_text)
            alignments.append((block, ref, chunk, subs))

    if not texts_to_embed:
        return []

    unique_texts = list(dict.fromkeys(texts_to_embed))
    vectors = {
        text: vector
        for text, vector in zip(
            unique_texts,
            get_embedding_service(settings).embed_queries(unique_texts),
            strict=True,
        )
    }

    embeds: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    threshold = settings.rag_step_align_min_score

    for block, ref, chunk, subs in alignments:
        best_sub = _best_sub_for_block(
            str(block.get("text") or "").strip(),
            subs,
            vectors,
            threshold=threshold,
        )
        if best_sub is None:
            continue

        assets_by_id = _assets_by_id(chunk)
        for asset_id in best_sub.get("asset_ids") or []:
            asset = assets_by_id.get(str(asset_id))
            if asset is None:
                continue
            payload = _embed_for_asset(
                chunk,
                asset,
                block_index=int(block["block_index"]),
                ref=ref,
            )
            if payload is None:
                continue
            dedupe_key = embed_dedupe_key(payload)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            embeds.append(payload)

    return embeds
