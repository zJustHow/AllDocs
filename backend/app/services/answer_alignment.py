"""Align answer sentences to chunk sub indexes via cosine similarity."""

from __future__ import annotations

import math
import re
from typing import Any

from app.config import Settings, get_settings
from app.services.chunk_alignment import build_chunk_sub_index
from app.services.embedding_provider import get_embedding_service
from app.services.shared_contract import (
    embed_dedupe_key,
    inline_citation_ref_pattern,
    strip_inline_markers,
)
from app.services.embeds_util import _embed_for_asset
from app.services.visual_asset_util import chunk_visual_assets

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?；;:])\s*")
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


def split_answer_sentences(answer: str) -> list[dict[str, Any]]:
    """Split answer into sentences; collect inline [n] refs in each sentence."""
    answer = answer.strip()
    if not answer:
        return []

    parts = [part.strip() for part in _SENTENCE_SPLIT.split(answer) if part.strip()]
    if not parts:
        parts = [answer]

    sentences: list[dict[str, Any]] = []
    for raw_text in parts:
        sentences.append(
            {
                "sentence_index": len(sentences),
                "text": strip_inline_markers(raw_text),
                "raw_text": raw_text,
                "citation_refs": _extract_citation_refs(raw_text),
            }
        )
    return sentences


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


def _best_sentence_for_sub(
    sentences: list[dict[str, Any]],
    ref: int,
    sub: dict[str, Any],
    vectors: dict[str, list[float]],
    *,
    threshold: float,
) -> int | None:
    index_text = str(sub.get("index_text") or sub.get("text") or "").strip()
    if not index_text:
        return None
    sub_vector = vectors.get(index_text)
    if sub_vector is None:
        return None

    best_index: int | None = None
    best_score = threshold
    for sentence in sentences:
        if ref not in (sentence.get("citation_refs") or []):
            continue
        sentence_text = str(sentence.get("text") or "").strip()
        if not sentence_text:
            continue
        sentence_vector = vectors.get(sentence_text)
        if sentence_vector is None:
            continue
        score = _cosine_similarity(sentence_vector, sub_vector)
        if score >= best_score:
            best_score = score
            best_index = int(sentence["sentence_index"])
    return best_index


def build_aligned_embeds(
    answer: str,
    cited_chunks: list[dict[str, Any]],
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return embeds aligned to cited answer sentences via sub similarity."""
    settings = settings or get_settings()
    sentences = split_answer_sentences(answer)
    if not sentences or not cited_chunks:
        return []

    cited_refs: list[int] = []
    seen_refs: set[int] = set()
    for sentence in sentences:
        for ref in sentence.get("citation_refs") or []:
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            cited_refs.append(ref)

    texts_to_embed: list[str] = []
    for sentence in sentences:
        sentence_text = str(sentence.get("text") or "").strip()
        if sentence_text:
            texts_to_embed.append(sentence_text)

    subs_by_ref: dict[int, list[dict[str, Any]]] = {}
    for ref in cited_refs:
        if ref < 1 or ref > len(cited_chunks):
            continue
        subs = _chunk_subs(cited_chunks[ref - 1])
        if not subs:
            continue
        subs_by_ref[ref] = subs
        for sub in subs:
            index_text = str(sub.get("index_text") or sub.get("text") or "").strip()
            if index_text:
                texts_to_embed.append(index_text)

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

    for ref, subs in subs_by_ref.items():
        chunk = cited_chunks[ref - 1]
        assets_by_id = _assets_by_id(chunk)
        for sub in subs:
            if not sub.get("asset_ids"):
                continue
            sentence_index = _best_sentence_for_sub(
                sentences,
                ref,
                sub,
                vectors,
                threshold=threshold,
            )
            if sentence_index is None:
                continue
            for asset_id in sub.get("asset_ids") or []:
                asset = assets_by_id.get(str(asset_id))
                if asset is None:
                    continue
                payload = _embed_for_asset(
                    chunk,
                    asset,
                    sentence_index=sentence_index,
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
