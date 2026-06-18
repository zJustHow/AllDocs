"""Attach visual assets to preceding text chunks by document reading order."""

from __future__ import annotations

_MAX_FALLBACK_PAGE_GAP = 2


def _is_attach_candidate(chunk: object) -> bool:
    page = getattr(chunk, "page", None)
    if page is None:
        return False
    return bool(getattr(chunk, "text", "").strip())


def pick_preceding_chunk(
    chunks: list,
    *,
    page: int,
    section: str | None,
    max_page_gap: int = _MAX_FALLBACK_PAGE_GAP,
) -> object | None:
    """Return the last text chunk before ``page`` within ``max_page_gap`` pages."""
    pool = [
        chunk
        for chunk in chunks
        if _is_attach_candidate(chunk)
        and int(getattr(chunk, "page")) <= page
        and page - int(getattr(chunk, "page")) <= max_page_gap
    ]
    if not pool:
        return None

    if section:
        section_pool = [chunk for chunk in pool if chunk.section == section]
        if section_pool:
            pool = section_pool

    return max(
        pool,
        key=lambda chunk: (
            int(getattr(chunk, "page")),
            int(getattr(chunk, "chunk_index", 0)),
        ),
    )
