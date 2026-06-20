"""Load ranked chunk records with document metadata and assets."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, ChunkAsset, Document
from app.services.asset_urls import asset_url
from app.services.chunk_index import (
    asset_caption_kwargs,
    captions_merged_into_text,
    chunk_display_snippet,
    chunk_rerank_text,
    format_context_body,
)

logger = logging.getLogger(__name__)


def parse_chunk_uuids(chunk_ids: list[str]) -> tuple[list[UUID], list[str]]:
    """Return valid UUIDs and any IDs that failed to parse."""
    valid: list[UUID] = []
    invalid: list[str] = []
    for chunk_id in chunk_ids:
        try:
            valid.append(UUID(chunk_id))
        except ValueError:
            invalid.append(chunk_id)
    return valid, invalid


async def load_ranked_chunks(
    db: AsyncSession,
    ranked_chunk_ids: list[str],
    score_map: dict[str, float],
) -> list[dict]:
    if not ranked_chunk_ids:
        return []

    chunk_uuids, invalid_ids = parse_chunk_uuids(ranked_chunk_ids)
    if invalid_ids:
        logger.warning("Skipping non-UUID chunk ids: %s", invalid_ids[:5])
    if not chunk_uuids:
        return []

    result = await db.execute(
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id.in_(chunk_uuids))
    )
    rows = {str(chunk.id): (chunk, document) for chunk, document in result.all()}

    asset_result = await db.execute(
        select(ChunkAsset)
        .where(ChunkAsset.chunk_id.in_(chunk_uuids))
        .order_by(ChunkAsset.asset_type, ChunkAsset.page)
    )
    assets_by_chunk: dict[str, list[ChunkAsset]] = {}
    for asset in asset_result.scalars():
        assets_by_chunk.setdefault(str(asset.chunk_id), []).append(asset)

    chunks: list[dict] = []
    for chunk_id in ranked_chunk_ids:
        if chunk_id not in rows:
            continue
        chunk, document = rows[chunk_id]
        chunk_assets = assets_by_chunk.get(chunk_id, [])
        caption_kwargs = asset_caption_kwargs(chunk.caption, chunk_assets)
        merged_into_text = captions_merged_into_text(chunk.text, **caption_kwargs)
        body_text = (
            chunk.text
            if merged_into_text
            else format_context_body(chunk.text, **caption_kwargs)
        )
        index_text = (
            chunk.text
            if merged_into_text
            else chunk_rerank_text(chunk.text, **caption_kwargs)
        )
        snippet = (
            chunk.text[:300]
            if merged_into_text
            else chunk_display_snippet(chunk.text, **caption_kwargs)
        )
        chunks.append(
            {
                "chunk_index": chunk.chunk_index,
                "chunk_id": chunk_id,
                "document_id": str(document.id),
                "document_name": document.name,
                "page": chunk.page,
                "section": chunk.section,
                "caption": chunk.caption,
                "score": score_map.get(chunk_id, 0.0),
                "snippet": snippet,
                "text": body_text,
                "index_text": index_text,
                "layout_bbox": chunk.layout_bbox,
                "layout_regions": chunk.layout_regions,
                "sub_index": chunk.sub_index,
                "assets": [
                    {
                        "asset_id": str(asset.id),
                        "type": asset.asset_type,
                        "page": asset.page,
                        "url": asset_url(asset.id),
                        "caption": asset.caption,
                        "vlm_caption": asset.vlm_caption,
                        "figure_caption": asset.figure_caption,
                        "figure_number": asset.figure_number,
                        "content_hash": asset.content_hash,
                        "bbox": asset.bbox,
                        "layout_regions": asset.layout_regions,
                    }
                    for asset in chunk_assets
                ],
            }
        )
    return chunks
