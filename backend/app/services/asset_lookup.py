"""Look up chunks by normalized figure/table number."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChunkAsset
from app.services.chunk_loader import load_ranked_chunks
from app.services.pdf_captions import normalize_figure_number

_ASSET_NUMBER_RE = re.compile(
    r"^\s*(?:(?:图|表)|(?i:figure|fig\.?|table))?\s*"
    r"(?P<chapter>\d+)\s*[-–—]\s*(?P<num>\d+)\s*$",
    re.IGNORECASE,
)
_BARE_NUMBER_RE = re.compile(
    r"^\s*(?P<chapter>\d+)\s*[-–—]\s*(?P<num>\d+)\s*$",
)


def parse_asset_number(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    for pattern in (_ASSET_NUMBER_RE, _BARE_NUMBER_RE):
        match = pattern.match(text)
        if match:
            return normalize_figure_number(match.group("chapter"), match.group("num"))
    return None


async def lookup_asset(
    db: AsyncSession,
    figure_number: str,
    *,
    kind: str | None = None,
    doc_ids: list[UUID] | None = None,
    document_id: UUID | None = None,
    top_k: int = 5,
) -> tuple[list[dict], str | None]:
    normalized = parse_asset_number(figure_number)
    if not normalized:
        return [], f"无效图号/表号：{figure_number}（示例：4-7、表2-1）"

    stmt = select(ChunkAsset.chunk_id).where(ChunkAsset.figure_number == normalized)
    if kind in {"figure", "table"}:
        stmt = stmt.where(ChunkAsset.asset_type == kind)
    if document_id is not None:
        stmt = stmt.where(ChunkAsset.document_id == document_id)
    elif doc_ids:
        stmt = stmt.where(ChunkAsset.document_id.in_(doc_ids))
    stmt = stmt.distinct().limit(max(1, top_k))

    result = await db.execute(stmt)
    chunk_ids = [str(row[0]) for row in result.all()]
    if not chunk_ids:
        label = kind or "图/表"
        return [], f"未找到 {label} {normalized}。"

    score_map = {chunk_id: 1.0 for chunk_id in chunk_ids}
    chunks = await load_ranked_chunks(db, chunk_ids, score_map)
    return chunks, None
