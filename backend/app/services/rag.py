import asyncio
import logging
import os
from uuid import UUID

from langdetect import DetectorFactory, detect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Chunk, Document
from app.services.chunk_filter import ChunkFilter, filter_citations
from app.services.embedding import EmbeddingService
from app.services.fulltext_store import FulltextStore
from app.services.hybrid import reciprocal_rank_fusion
from app.services.llm import LLMService, QueryIntent
from app.services.query_plan import QueryPlan, QueryPlannerService, SubQuery
from app.services.reranker import RerankerService
from app.services.vector_store import VectorStore

DetectorFactory.seed = 0
logger = logging.getLogger(__name__)


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
    return "Not found in the manual." if lang == "en" else "说明书中未找到相关信息。"


class RAGService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.embedding = EmbeddingService(self.settings)
        self.vector_store = VectorStore(self.settings)
        self.fulltext_store = (
            FulltextStore(self.settings) if self.settings.hybrid_enabled else None
        )
        self.llm = LLMService(self.settings)
        self.query_planner = QueryPlannerService(self.settings, self.llm)
        self.reranker = None
        if self.settings.rerank_enabled:
            if model_path_ready(self.settings.rerank_model):
                self.reranker = RerankerService(self.settings)
            else:
                logger.warning(
                    "Rerank model not found at %s; rerank disabled for this process",
                    self.settings.rerank_model,
                )

    async def _load_citations(
        self,
        db: AsyncSession,
        ranked_chunk_ids: list[str],
        score_map: dict[str, float],
    ) -> list[dict]:
        if not ranked_chunk_ids:
            return []

        chunk_uuids = [UUID(chunk_id) for chunk_id in ranked_chunk_ids]
        result = await db.execute(
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.id.in_(chunk_uuids))
        )
        rows = {str(chunk.id): (chunk, document) for chunk, document in result.all()}

        citations: list[dict] = []
        for chunk_id in ranked_chunk_ids:
            if chunk_id not in rows:
                continue
            chunk, document = rows[chunk_id]
            citations.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": str(document.id),
                    "document_name": document.name,
                    "page": chunk.page,
                    "section": chunk.section,
                    "chunk_type": chunk.chunk_type,
                    "content_role": chunk.content_role,
                    "score": score_map.get(chunk_id, 0.0),
                    "snippet": chunk.text[:300],
                    "text": chunk.text,
                }
            )
        return citations

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
        vector_score_map = {str(hit.id): float(hit.score) for hit in vector_hits}

        if bm25_hits:
            bm25_ids = [chunk_id for chunk_id, _ in bm25_hits]
            fused = reciprocal_rank_fusion(
                [vector_ids, bm25_ids],
                top_k=retrieve_k,
                k=self.settings.hybrid_rrf_k,
            )
            return [chunk_id for chunk_id, _ in fused], dict(fused)

        return vector_ids, vector_score_map

    async def _retrieve_once(
        self,
        db: AsyncSession,
        question: str,
        chunk_filter: ChunkFilter,
        *,
        top_k: int | None = None,
        skip_rerank: bool = False,
        query_vector: list[float] | None = None,
    ) -> list[dict]:
        use_extended_retrieval = self.reranker or self.settings.hybrid_enabled
        retrieve_k = self.settings.rag_retrieve_k if use_extended_retrieval else self.settings.rag_top_k
        final_k = top_k or self.settings.rag_top_k

        if query_vector is None:
            query_vector = await asyncio.to_thread(self.embedding.embed_query, question)

        ranked_chunk_ids, score_map = await self._search_hybrid(
            question,
            query_vector,
            retrieve_k,
            chunk_filter,
        )

        citations = await self._load_citations(db, ranked_chunk_ids, score_map)
        citations = filter_citations(citations, chunk_filter)
        if not citations:
            return []

        if self.reranker and not skip_rerank:
            citations = self.reranker.rerank(question, citations)
        return citations[:final_k]

    def _merge_sub_query_filter(self, base: ChunkFilter, sub: SubQuery) -> ChunkFilter:
        merged = base.model_copy(deep=True)
        if sub.content_roles:
            merged.content_roles = sub.content_roles
        if sub.chunk_types:
            merged.chunk_types = sub.chunk_types
        if sub.section_hints:
            merged.section_contains = sub.section_hints[0]
        return merged

    async def _retrieve_with_relaxation(
        self,
        db: AsyncSession,
        question: str,
        chunk_filter: ChunkFilter,
    ) -> list[dict]:
        if not chunk_filter.has_metadata_constraints():
            return await self._retrieve_once(db, question, chunk_filter) or []

        query_vector = await asyncio.to_thread(self.embedding.embed_query, question)
        broad_filter = chunk_filter.broad_filter()
        broad_citations, strict_citations = await asyncio.gather(
            self._retrieve_once(db, question, broad_filter, query_vector=query_vector),
            self._retrieve_once(db, question, chunk_filter, query_vector=query_vector),
        )

        if strict_citations:
            if broad_citations and broad_filter.model_dump_json() != chunk_filter.model_dump_json():
                logger.info(
                    "Metadata filter applied; strict=%s",
                    chunk_filter.model_dump(exclude_none=True),
                )
            return strict_citations

        if broad_citations:
            logger.info(
                "Broad retrieval fallback after strict filter returned empty; original=%s",
                chunk_filter.model_dump(exclude_none=True),
            )
        return broad_citations or []

    async def _retrieve_troubleshooting_slot(
        self,
        db: AsyncSession,
        sub: SubQuery,
        base_filter: ChunkFilter,
        *,
        per_slot: int,
    ) -> list[dict]:
        slot_filter = self._merge_sub_query_filter(base_filter, sub)
        slot_citations = await self._retrieve_once(
            db,
            sub.query,
            slot_filter,
            top_k=per_slot,
            skip_rerank=True,
        )
        if slot_citations:
            return slot_citations

        broad_slot_filter = slot_filter.broad_filter()
        return await self._retrieve_once(
            db,
            sub.query,
            broad_slot_filter,
            top_k=per_slot,
            skip_rerank=True,
        ) or []

    async def _retrieve_troubleshooting(
        self,
        db: AsyncSession,
        question: str,
        plan: QueryPlan,
        base_filter: ChunkFilter,
    ) -> list[dict]:
        per_slot = min(
            plan.top_k_per_slot,
            self.settings.rag_troubleshooting_top_k_per_slot,
        )
        max_total = self.settings.rag_troubleshooting_max_total
        collected: list[dict] = []
        seen: set[str] = set()

        slot_results = await asyncio.gather(
            *[
                self._retrieve_troubleshooting_slot(
                    db,
                    sub,
                    base_filter,
                    per_slot=per_slot,
                )
                for sub in plan.sub_queries
            ]
        )

        for sub, slot_citations in zip(plan.sub_queries, slot_results, strict=True):
            for citation in slot_citations:
                chunk_id = citation["chunk_id"]
                if chunk_id in seen:
                    continue
                seen.add(chunk_id)
                enriched = dict(citation)
                enriched["slot"] = sub.slot
                collected.append(enriched)

        if not collected:
            logger.info("Troubleshooting slot retrieval empty; falling back to broad retrieval")
            return await self._retrieve_with_relaxation(db, question, base_filter)

        if self.reranker:
            collected = self.reranker.rerank(question, collected)
        return collected[:max_total]

    async def search_chunks(
        self,
        db: AsyncSession,
        question: str,
        chunk_filter: ChunkFilter,
        *,
        top_k: int | None = None,
    ) -> list[dict]:
        if chunk_filter.has_metadata_constraints():
            return await self._retrieve_with_relaxation(db, question, chunk_filter)
        return await self._retrieve_once(db, question, chunk_filter, top_k=top_k) or []

    async def search_troubleshooting(
        self,
        db: AsyncSession,
        question: str,
        base_filter: ChunkFilter,
    ) -> tuple[list[dict], QueryIntent]:
        plan = await self.query_planner.plan(question)
        citations = await self._retrieve_troubleshooting(db, question, plan, base_filter)
        return citations, plan.intent

    async def read_chunks(
        self,
        db: AsyncSession,
        chunk_ids: list[str],
    ) -> list[dict]:
        score_map = {chunk_id: 1.0 for chunk_id in chunk_ids}
        return await self._load_citations(db, chunk_ids, score_map)

    def build_context(self, citations: list[dict]) -> str:
        parts: list[str] = []
        for index, item in enumerate(citations, start=1):
            header = f"[{index}] {item['document_name']}"
            if item.get("slot"):
                header += f" slot={item['slot']}"
            if item.get("content_role"):
                header += f" role={item['content_role']}"
            if item.get("page"):
                header += f" p.{item['page']}"
            if item.get("section"):
                header += f" §{item['section']}"
            parts.append(f"{header}\n{item['text']}")
        return "\n\n---\n\n".join(parts)
