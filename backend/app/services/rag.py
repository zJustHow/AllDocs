import asyncio
import logging
import os
from uuid import UUID

from langdetect import DetectorFactory, detect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Chunk, ChunkAsset, Document
from app.services.asset_urls import asset_url
from app.services.chunk_index import (
    asset_caption_kwargs,
    captions_merged_into_text,
    chunk_display_snippet,
    chunk_rerank_text,
    format_context_body,
)
from app.services.chunk_filter import ChunkFilter, filter_chunks, chunk_asset_types
from app.services.embedding_provider import get_embedding_service
from app.services.fulltext_store import FulltextStore
from app.services.hybrid import reciprocal_rank_fusion
from app.services.reranker_provider import get_reranker_service
from app.services.toc_lookup import ResolvedSection, resolve_section
from app.services.vector_store import VectorStore

DetectorFactory.seed = 0
logger = logging.getLogger(__name__)

# Internal delimiter between evidence blocks in <context>; not shown to users.
_CONTEXT_CHUNK_SEPARATOR = "\n\n<!-- chunk -->\n\n"


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


def model_path_ready(model_ref: str) -> bool:
    if not model_ref.startswith("/"):
        return True
    return os.path.isfile(os.path.join(model_ref, "config.json"))


def detect_language(text: str) -> str:
    try:
        lang = detect(text)
        return "zh" if lang.startswith("zh") else "en" if lang == "en" else lang
    except Exception:
        return "zh"


def not_found_message(lang: str) -> str:
    return "Not found in the operation guide." if lang == "en" else "操作指南中未找到相关信息。"


def low_relevance_message(lang: str) -> str:
    if lang == "en":
        return (
            "The operation guide was searched, but the retrieved passages are not relevant enough "
            "to answer confidently. Try rephrasing with more specific keywords, model numbers, "
            "or fault symptoms."
        )
    return (
        "操作指南里检索到了片段，但与您的问题相关性不足，暂时无法据此给出可靠回答。"
        "建议补充更具体的关键词、型号或故障现象后重新提问。"
    )


def _min_relevance_score(settings: Settings, *, reranker_active: bool = False) -> float:
    if reranker_active:
        return settings.rag_min_rerank_score
    return settings.rag_min_retrieval_score


def _semantic_primary_scores(evidence: list[dict]) -> list[float]:
    scores: list[float] = []
    for chunk in evidence:
        if not chunk.get("from_semantic_search"):
            continue
        score = chunk.get("score")
        if score is not None:
            scores.append(float(score))
    return scores


def resolve_retrieval_fallback(
    lang: str,
    *,
    evidence: list[dict],
    settings: Settings,
    reranker_active: bool = False,
) -> str | None:
    """Return a user-facing fallback when synthesis should be skipped, else None."""
    semantic_evidence = [chunk for chunk in evidence if chunk.get("from_semantic_search")]
    if semantic_evidence:
        scores = _semantic_primary_scores(evidence)
        threshold = _min_relevance_score(settings, reranker_active=reranker_active)
        if scores and max(scores) < threshold:
            return low_relevance_message(lang)
        return None

    if not evidence:
        return not_found_message(lang)

    return None


class RAGService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.embedding = get_embedding_service(self.settings)
        self.vector_store = VectorStore(self.settings)
        self.fulltext_store = (
            FulltextStore(self.settings) if self.settings.hybrid_enabled else None
        )
        self.reranker = None
        if self.settings.rerank_enabled:
            if self.settings.inference_url or model_path_ready(self.settings.rerank_model):
                self.reranker = get_reranker_service(self.settings)
            else:
                logger.warning(
                    "Rerank model not found at %s; rerank disabled for this process",
                    self.settings.rerank_model,
                )

    async def _load_chunks(
        self,
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

    async def _search_hybrid(
        self,
        question: str,
        query_vector: list[float],
        retrieve_k: int,
        effective_filter: ChunkFilter,
    ) -> tuple[list[str], dict[str, float]]:
        async def vector_search() -> list:
            return await asyncio.to_thread(
                self.vector_store.search,
                query_vector,
                retrieve_k,
                effective_filter,
            )

        async def bm25_search() -> list[tuple[str, float]]:
            if not self.fulltext_store:
                return []
            try:
                return await asyncio.to_thread(
                    self.fulltext_store.search,
                    question,
                    retrieve_k,
                    effective_filter,
                )
            except Exception:
                return []

        vector_hits, bm25_hits = await asyncio.gather(vector_search(), bm25_search())

        vector_ids = [str(hit.id) for hit in vector_hits]

        if bm25_hits:
            bm25_ids = [chunk_id for chunk_id, _ in bm25_hits]
            fused = reciprocal_rank_fusion(
                [vector_ids, bm25_ids],
                top_k=retrieve_k,
                k=self.settings.hybrid_rrf_k,
            )
            return [chunk_id for chunk_id, _ in fused], dict(fused)

        vector_score_map = {str(hit.id): float(hit.score) for hit in vector_hits}
        return vector_ids, vector_score_map

    async def _embed_query(self, question: str) -> list[float]:
        return await self.embedding.embed_query_async(question)

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return await self.embedding.embed_queries_async(texts)

    async def _embed_queries(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_queries(texts)

    async def _rerank(self, question: str, chunks: list[dict]) -> list[dict]:
        return await self.reranker.rerank_async(question, chunks)

    async def _retrieve_once(
        self,
        db: AsyncSession,
        question: str,
        chunk_filter: ChunkFilter,
        *,
        top_k: int | None = None,
        query_vector: list[float] | None = None,
    ) -> list[dict]:
        use_extended_retrieval = self.reranker or self.settings.hybrid_enabled
        retrieve_k = self.settings.rag_retrieve_k if use_extended_retrieval else self.settings.rag_top_k
        final_k = top_k or self.settings.rag_top_k

        if query_vector is None:
            query_vector = await self._embed_query(question)

        ranked_chunk_ids, score_map = await self._search_hybrid(
            question,
            query_vector,
            retrieve_k,
            chunk_filter,
        )

        chunks = await self._load_chunks(db, ranked_chunk_ids, score_map)
        chunks = filter_chunks(chunks, chunk_filter)
        if not chunks:
            return []

        if self.reranker:
            chunks = await self._rerank(question, chunks)
        return chunks[:final_k]

    async def _retrieve_with_relaxation(
        self,
        db: AsyncSession,
        question: str,
        chunk_filter: ChunkFilter,
        *,
        query_vector: list[float] | None = None,
    ) -> list[dict]:
        if not chunk_filter.has_metadata_constraints():
            return await self._retrieve_once(
                db, question, chunk_filter, query_vector=query_vector
            ) or []

        if query_vector is None:
            query_vector = await self._embed_query(question)
        broad_filter = chunk_filter.broad_filter()

        strict_chunks = await self._retrieve_once(
            db, question, chunk_filter, query_vector=query_vector
        )
        if strict_chunks:
            if broad_filter.model_dump_json() != chunk_filter.model_dump_json():
                logger.info(
                    "Metadata filter applied; strict=%s",
                    chunk_filter.model_dump(exclude_none=True),
                )
            return strict_chunks

        broad_chunks = await self._retrieve_once(
            db, question, broad_filter, query_vector=query_vector
        )
        if broad_chunks:
            logger.info(
                "Broad retrieval fallback after strict filter returned empty; original=%s",
                chunk_filter.model_dump(exclude_none=True),
            )
        return broad_chunks or []

    async def search_chunks(
        self,
        db: AsyncSession,
        question: str,
        chunk_filter: ChunkFilter,
        *,
        top_k: int | None = None,
        query_vector: list[float] | None = None,
    ) -> list[dict]:
        if chunk_filter.has_metadata_constraints():
            return await self._retrieve_with_relaxation(
                db, question, chunk_filter, query_vector=query_vector
            )
        return await self._retrieve_once(
            db, question, chunk_filter, top_k=top_k, query_vector=query_vector
        ) or []

    async def read_chunks(
        self,
        db: AsyncSession,
        chunk_ids: list[str],
    ) -> list[dict]:
        score_map = {chunk_id: 1.0 for chunk_id in chunk_ids}
        return await self._load_chunks(db, chunk_ids, score_map)

    async def read_neighbor_chunks(
        self,
        db: AsyncSession,
        chunk_id: str,
        *,
        before: int = 1,
        after: int = 1,
    ) -> tuple[list[dict], str | None]:
        """Load anchor chunk and up to ``before``/``after`` neighbors by chunk_index."""
        chunk_uuids, _invalid = parse_chunk_uuids([chunk_id])
        if not chunk_uuids:
            return [], f"无效 chunk_id：{chunk_id}"

        anchor_id = chunk_uuids[0]
        anchor_row = await db.execute(select(Chunk).where(Chunk.id == anchor_id))
        anchor = anchor_row.scalar_one_or_none()
        if anchor is None:
            return [], "未找到锚点 chunk。"

        index_lo = max(0, anchor.chunk_index - before)
        index_hi = anchor.chunk_index + after
        result = await db.execute(
            select(Chunk.id)
            .where(
                Chunk.document_id == anchor.document_id,
                Chunk.chunk_index >= index_lo,
                Chunk.chunk_index <= index_hi,
            )
            .order_by(Chunk.chunk_index)
        )
        ordered_ids = [str(row[0]) for row in result.all()]
        if not ordered_ids:
            return [], "未找到相邻 chunk。"

        score_map = {cid: 1.0 for cid in ordered_ids}
        return await self._load_chunks(db, ordered_ids, score_map), None

    async def read_pages(
        self,
        db: AsyncSession,
        *,
        page: int | None = None,
        page_gte: int | None = None,
        page_lte: int | None = None,
        document_id: UUID | None = None,
        doc_ids: list[UUID] | None = None,
        max_chunks: int = 30,
    ) -> tuple[list[dict], str | None]:
        if page is not None:
            page_gte = page
            page_lte = page
        if page_gte is None and page_lte is None:
            return [], "read_pages 需要 page 或 page_gte/page_lte。"

        stmt = (
            select(Chunk.id, Document.name)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.page.is_not(None))
        )
        if page_gte is not None:
            stmt = stmt.where(Chunk.page >= page_gte)
        if page_lte is not None:
            stmt = stmt.where(Chunk.page <= page_lte)
        if document_id is not None:
            stmt = stmt.where(Chunk.document_id == document_id)
        elif doc_ids:
            stmt = stmt.where(Chunk.document_id.in_(doc_ids))
        stmt = stmt.order_by(Document.name, Chunk.chunk_index).limit(max(1, max_chunks))

        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return [], "未找到对应页码的 chunk。"

        ordered_ids = [str(row[0]) for row in rows]
        score_map = {chunk_id: 1.0 for chunk_id in ordered_ids}
        return await self._load_chunks(db, ordered_ids, score_map), None

    async def search_keyword(
        self,
        db: AsyncSession,
        query: str,
        chunk_filter: ChunkFilter,
        *,
        top_k: int | None = None,
    ) -> list[dict]:
        if not self.fulltext_store:
            return []

        final_k = top_k or self.settings.rag_top_k
        hits = await asyncio.to_thread(
            self.fulltext_store.search_keyword,
            query,
            final_k,
            chunk_filter,
        )
        if not hits:
            return []

        ranked_ids = [chunk_id for chunk_id, _ in hits]
        score_map = {chunk_id: score for chunk_id, score in hits}
        return await self._load_chunks(db, ranked_ids, score_map)

    async def read_section(
        self,
        db: AsyncSession,
        question: str,
        doc_ids: list[UUID] | None,
        *,
        section: str | None = None,
        document_id: UUID | None = None,
        max_chunks: int = 30,
    ) -> tuple[list[dict], ResolvedSection | None, str | None]:
        resolved = await resolve_section(
            db,
            question,
            doc_ids,
            section=section,
            document_id=document_id,
        )
        if resolved is None:
            return [], None, "未找到匹配章节。"

        chunks, error = await self.read_pages(
            db,
            page_gte=resolved.start_page,
            page_lte=resolved.end_page,
            document_id=resolved.document_id,
            doc_ids=doc_ids,
            max_chunks=max_chunks,
        )
        if error:
            return [], resolved, error

        section_path = resolved.section_path.casefold()
        if section_path:
            filtered = [
                chunk
                for chunk in chunks
                if not chunk.get("section")
                or section_path in str(chunk.get("section")).casefold()
            ]
            if filtered:
                chunks = filtered

        return chunks, resolved, None

    def build_context(self, chunks: list[dict]) -> str:
        parts: list[str] = []
        for index, item in enumerate(chunks, start=1):
            header = f"[{index}] {item['document_name']}"
            if item.get("page"):
                header += f" p.{item['page']}"
            if item.get("section"):
                header += f" §{item['section']}"
            asset_types = chunk_asset_types(item)
            if asset_types:
                header += f" assets={','.join(asset_types)}"
            if item.get("assets"):
                header += " (visual)"
            parts.append(f"{header}\n{item['text']}")
        return _CONTEXT_CHUNK_SEPARATOR.join(parts)
