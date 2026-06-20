import re

from app.services.pdf_layout_regions import normalize_layout_regions
from app.services.shared_contract import (
    inline_citation_ref_pattern,
    strip_inline_markers,
)

INLINE_CITATION_REF = inline_citation_ref_pattern()

def strip_inline_citation_markers(content: str) -> str:
    """Remove inline [n] / 【n】 / {{embed:n}} markers (e.g. before TTS)."""
    return strip_inline_markers(content)


def renumber_answer_citations(answer: str, context_chunks: list[dict]) -> tuple[str, list[dict], dict[int, int]]:
    """Renumber inline [n] markers from 1 by first appearance; keep only cited sources."""
    seen_old_indices: list[int] = []
    seen_set: set[int] = set()

    for match in INLINE_CITATION_REF.finditer(answer):
        old_num = int(match.group(1) or match.group(2))
        old_index = old_num - 1
        if old_index < 0 or old_index >= len(context_chunks) or old_index in seen_set:
            continue
        seen_set.add(old_index)
        seen_old_indices.append(old_index)

    if not seen_old_indices:
        return answer, [], {}

    old_to_new = {old_index + 1: new_num for new_num, old_index in enumerate(seen_old_indices, start=1)}
    new_chunks = [context_chunks[old_index] for old_index in seen_old_indices]

    def replace_ref(match: re.Match[str]) -> str:
        old_num = int(match.group(1) or match.group(2))
        new_num = old_to_new.get(old_num)
        if new_num is None:
            return match.group(0)
        if match.group(2):
            return f"【{new_num}】"
        return f"[{new_num}]"

    return INLINE_CITATION_REF.sub(replace_ref, answer), new_chunks, old_to_new


def _finalize_answer_sync(
    answer: str,
    context_chunks: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    from app.services.answer_alignment import build_aligned_embeds
    from app.services.embeds_util import public_embeds

    answer, cited_chunks, _citation_renumber = renumber_answer_citations(answer, context_chunks)
    embeds = build_aligned_embeds(answer, cited_chunks)
    return answer, public_citations(cited_chunks), public_embeds(embeds)


def finalize_answer(
    answer: str,
    context_chunks: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    return _finalize_answer_sync(answer, context_chunks)


async def finalize_answer_async(
    answer: str,
    context_chunks: list[dict],
) -> tuple[str, list[dict], list[dict]]:
    import asyncio

    return await asyncio.to_thread(_finalize_answer_sync, answer, context_chunks)


def public_citations(chunks: list[dict]) -> list[dict]:
    return [
        {
            "document_id": item["document_id"],
            "document_name": item["document_name"],
            "page": item["page"],
            "section": item["section"],
            "snippet": item["snippet"],
            "score": item["score"],
            "regions": normalize_layout_regions(item.get("layout_regions")),
        }
        for item in chunks
    ]


__all__ = [
    "finalize_answer",
    "finalize_answer_async",
    "public_citations",
    "strip_inline_citation_markers",
]
