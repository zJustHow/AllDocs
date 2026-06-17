import re

from app.services.shared_contract import (
    citation_ref_pattern,
    inline_citation_ref_pattern,
    strip_inline_markers,
)

TRAILING_SOURCES_SECTION = re.compile(
    r"\n+(?:#{1,3}\s*)?(?:来源|引用|References|Sources)\s*[:：]?\s*\n[\s\S]*$",
    re.IGNORECASE,
)
INLINE_CITATION_REF = inline_citation_ref_pattern()


def strip_inline_citation_markers(content: str) -> str:
    """Remove inline [n] / 【n】 / {{embed:n}} markers (e.g. before TTS)."""
    return strip_inline_markers(content)


def normalize_answer_citations(answer: str) -> str:
    """Keep inline [n] markers and drop trailing source-list sections."""
    return TRAILING_SOURCES_SECTION.sub("", answer).strip()


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


def finalize_answer(answer: str, context_chunks: list[dict]) -> tuple[str, list[dict], list[dict]]:
    from app.services.embeds_util import (
        auto_insert_embed_markers,
        dedupe_answer_embed_markers,
        public_embeds,
        renumber_embed_markers,
    )

    answer = normalize_answer_citations(answer)
    answer, cited_chunks, citation_renumber = renumber_answer_citations(answer, context_chunks)
    answer = renumber_embed_markers(answer, citation_renumber)
    answer = auto_insert_embed_markers(answer, cited_chunks)
    answer, embeds = dedupe_answer_embed_markers(answer, cited_chunks)
    return answer, public_citations(cited_chunks), public_embeds(embeds)


def _resolve_citation_bbox(chunk: dict) -> list[float] | None:
    text = (chunk.get("text") or chunk.get("snippet") or "").strip()
    layout = chunk.get("layout_bbox")
    if layout and len(layout) == 4 and text:
        return [float(value) for value in layout]

    for asset in chunk.get("assets") or []:
        bbox = asset.get("bbox")
        if bbox and len(bbox) == 4:
            return [float(value) for value in bbox]

    if layout and len(layout) == 4:
        return [float(value) for value in layout]
    return None


def public_citations(chunks: list[dict]) -> list[dict]:
    return [
        {
            "document_id": item["document_id"],
            "document_name": item["document_name"],
            "page": item["page"],
            "section": item["section"],
            "snippet": item["snippet"],
            "score": item["score"],
            "bbox": _resolve_citation_bbox(item),
        }
        for item in chunks
    ]


__all__ = ["citation_ref_pattern", "finalize_answer", "public_citations", "strip_inline_citation_markers"]
