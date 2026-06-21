import asyncio
import logging
import os
from dataclasses import dataclass
from uuid import UUID

from langdetect import DetectorFactory, detect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Chunk, Document
from app.services.chunk_filter import ChunkFilter, filter_chunks
from app.services.chunk_format import format_chunk_header
from app.services.chunk_loader import load_ranked_chunks, parse_chunk_uuids
from app.services.embedding_provider import get_embedding_service
from app.services.fulltext_store import FulltextStore
from app.services.hybrid import reciprocal_rank_fusion
from app.services.reranker_provider import get_reranker_service
from app.services.toc_lookup import ResolvedSection, resolve_section
from app.services.vector_store import VectorStore
from app.observability import timed_stage

DetectorFactory.seed = 0
logger = logging.getLogger(__name__)

# Internal delimiter between evidence blocks in <context>; not shown to users.
_CONTEXT_CHUNK_SEPARATOR = "\n\n<!-- chunk -->\n\n"


@dataclass(frozen=True)
class SectionReadPage:
    offset: int
    limit: int
    has_more: bool
    next_offset: int | None


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


def resolve_retrieval_fallback(
    lang: str,
    *,
    evidence: list[dict],
) -> str | None:
    """Return a user-facing fallback when synthesis should be skipped, else None."""
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

    async def load_chunks(
        self,
        db: AsyncSession,
        ranked_chunk_ids: list[str],
        score_map: dict[str, float],
    ) -> list[dict]:
        return await load_ranked_chunks(db, ranked_chunk_ids, score_map)

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
            except Exception as exc:
                logger.warning(
                    "BM25 search failed; continuing with vector results only: %s",
                    exc,
                )
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
        with timed_stage("rag", "embed_query"):
            return await self.embedding.embed_query_async(question)

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        with timed_stage("rag", "embed_queries", text_count=len(texts)):
            return await self.embedding.embed_queries_async(texts)

    async def _rerank(self, question: str, chunks: list[dict]) -> list[dict]:
        with timed_stage("rag", "rerank", chunk_count=len(chunks)):
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

        with timed_stage("rag", "hybrid_search", retrieve_k=retrieve_k):
            ranked_chunk_ids, score_map = await self._search_hybrid(
                question,
                query_vector,
                retrieve_k,
                chunk_filter,
            )

        with timed_stage("rag", "load_chunks", chunk_count=len(ranked_chunk_ids)):
            chunks = await self.load_chunks(db, ranked_chunk_ids, score_map)
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
        return await self.load_chunks(db, ordered_ids, score_map), None

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
        offset: int = 0,
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
        stmt = (
            stmt.order_by(Document.name, Chunk.chunk_index)
            .offset(max(0, offset))
            .limit(max(1, max_chunks))
        )

        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return [], "未找到对应页码的 chunk。"

        ordered_ids = [str(row[0]) for row in rows]
        score_map = {chunk_id: 1.0 for chunk_id in ordered_ids}
        return await self.load_chunks(db, ordered_ids, score_map), None

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
        return await self.load_chunks(db, ranked_ids, score_map)

    async def read_section(
        self,
        db: AsyncSession,
        question: str,
        doc_ids: list[UUID] | None,
        *,
        section: str | None = None,
        document_id: UUID | None = None,
        max_chunks: int = 30,
        offset: int = 0,
    ) -> tuple[list[dict], ResolvedSection | None, SectionReadPage | None, str | None]:
        resolved = await resolve_section(
            db,
            question,
            doc_ids,
            section=section,
            document_id=document_id,
        )
        if resolved is None:
            return [], None, None, "未找到匹配章节。"

        chunks, error = await self.read_pages(
            db,
            page_gte=resolved.start_page,
            page_lte=resolved.end_page,
            document_id=resolved.document_id,
            doc_ids=doc_ids,
            max_chunks=max_chunks + 1,
            offset=offset,
        )
        if error:
            return [], resolved, None, error

        has_more = len(chunks) > max_chunks
        chunks = chunks[:max_chunks]
        page = SectionReadPage(
            offset=max(0, offset),
            limit=max_chunks,
            has_more=has_more,
            next_offset=max(0, offset) + max_chunks if has_more else None,
        )

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

        return chunks, resolved, page, None

    def build_context(self, chunks: list[dict]) -> str:
        parts: list[str] = []
        for index, item in enumerate(chunks, start=1):
            header = format_chunk_header(item, index=index)
            parts.append(f"{header}\n{item['text']}")
        return _CONTEXT_CHUNK_SEPARATOR.join(parts)
