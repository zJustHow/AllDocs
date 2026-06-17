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
_PIPE_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")
_PIPE_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def _paragraph_at_position(answer: str, pos: int) -> str:
    start = answer.rfind("\n\n", 0, pos)
    start = 0 if start < 0 else start + 2
    end = answer.find("\n\n", pos)
    end = len(answer) if end < 0 else end
    return answer[start:end]


def _insert_at_section_heading(answer: str, chunk: dict) -> int | None:
    """Prefer inserting near the chunk's document section title in the answer."""
    section = (chunk.get("section") or "").strip()
    if not section:
        return None

    candidates: list[str] = []
    seen: set[str] = set()
    for part in section.split(">"):
        part = part.strip()
        if part and part not in seen:
            seen.add(part)
            candidates.append(part)
    if section not in seen:
        candidates.append(section)

    best_idx: int | None = None
    for candidate in candidates:
        if len(candidate) < 2:
            continue
        for needle in (f"## {candidate}", f"### {candidate}", candidate):
            idx = answer.find(needle)
            if idx >= 0 and (best_idx is None or idx < best_idx):
                best_idx = idx
    return best_idx


def _best_citation_insert_at(answer: str, ref: int, chunk: dict) -> int | None:
    heading_at = _insert_at_section_heading(answer, chunk)
    if heading_at is not None:
        return heading_at

    matches = list(citation_ref_pattern(ref).finditer(answer))
    if not matches:
        return None

    chunk_section = (chunk.get("section") or chunk.get("caption") or "").strip()
    if chunk_section:
        for match in matches:
            paragraph = _paragraph_at_position(answer, match.start())
            first_line = paragraph.split("\n", 1)[0].strip().lstrip("*").rstrip("*")
            if (
                chunk_section in paragraph
                or first_line in chunk_section
                or chunk_section in first_line
            ):
                return match.start()

    return matches[0].start()


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


def _contains_markdown_pipe_table(text: str) -> bool:
    """True when text includes a GFM pipe table (header, separator, and body row)."""
    lines = [line for line in text.splitlines() if line.strip()]
    for index in range(len(lines) - 2):
        if (
            _PIPE_TABLE_ROW.match(lines[index])
            and _PIPE_TABLE_SEPARATOR.match(lines[index + 1])
            and _PIPE_TABLE_ROW.match(lines[index + 2])
        ):
            return True
    return False


def _chunk_has_tabular_asset_caption(chunk: dict) -> bool:
    """Table assets store markdown summaries in assets[].caption."""
    asset = primary_visual_asset(chunk)
    if asset is None or asset.get("type") != "table":
        return False
    caption = str(asset.get("caption") or "").strip()
    return bool(caption) and _contains_markdown_pipe_table(caption)


def _context_near_citation(answer: str, ref: int) -> str:
    """Paragraph(s) around [ref]: table may sit just before or after the citation."""
    paragraphs = [part for part in re.split(r"\n{2,}", answer) if part.strip()]
    target_index: int | None = None
    for index, paragraph in enumerate(paragraphs):
        if citation_ref_pattern(ref).search(paragraph):
            target_index = index
            break
    if target_index is None:
        return ""

    indices = {target_index}
    if target_index > 0:
        indices.add(target_index - 1)
    if target_index + 1 < len(paragraphs):
        indices.add(target_index + 1)
    return "\n\n".join(paragraphs[index] for index in sorted(indices))


def _should_skip_auto_embed(answer: str, ref: int, chunk: dict) -> bool:
    """Skip auto embed when the answer already reproduces a table asset caption."""
    if not _chunk_has_tabular_asset_caption(chunk):
        return False
    return _contains_markdown_pipe_table(_context_near_citation(answer, ref))


def evidence_has_visual(chunks: list[dict]) -> bool:
    return any(_chunk_should_embed(chunk) for chunk in chunks)


def _chunk_embed_allowed(
    chunk: dict,
    allowed_embed_asset_ids: frozenset[str] | None,
) -> bool:
    if allowed_embed_asset_ids is None:
        return True
    asset = primary_visual_asset(chunk)
    if asset is None or not asset.get("asset_id"):
        return False
    return str(asset["asset_id"]) in allowed_embed_asset_ids


def auto_insert_embed_markers(
    answer: str,
    cited_chunks: list[dict],
    *,
    allowed_embed_asset_ids: frozenset[str] | None = None,
) -> str:
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
        if not _chunk_embed_allowed(chunk, allowed_embed_asset_ids):
            continue
        if _should_skip_auto_embed(answer, ref, chunk):
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
    *,
    allowed_embed_asset_ids: frozenset[str] | None = None,
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
        if not _chunk_embed_allowed(chunk, allowed_embed_asset_ids):
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
