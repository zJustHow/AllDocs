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
    chunk_display_snippet,
    chunk_rerank_text,
    format_context_body,
)
from app.services.chunk_filter import ChunkFilter, filter_chunks
from app.services.embedding import EmbeddingService
from app.services.fulltext_store import FulltextStore
from app.services.hybrid import reciprocal_rank_fusion
from app.services.reranker import RerankerService
from app.services.vector_store import VectorStore

DetectorFactory.seed = 0
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


def low_relevance_message(lang: str) -> str:
    if lang == "en":
        return (
            "The manual was searched, but the retrieved passages are not relevant enough "
            "to answer confidently. Try rephrasing with more specific keywords, model numbers, "
            "or fault symptoms."
        )
    return (
        "说明书里检索到了片段，但与您的问题相关性不足，暂时无法据此给出可靠回答。"
        "建议补充更具体的关键词、型号或故障现象后重新提问。"
    )


def _min_relevance_score(settings: Settings) -> float:
    if settings.rerank_enabled:
        return settings.rag_min_rerank_score
    return settings.rag_min_retrieval_score


def _semantic_primary_scores(evidence: list[dict]) -> list[float]:
    scores: list[float] = []
    for chunk in evidence:
        if not chunk.get("from_semantic_search"):
            continue
        if chunk.get("is_neighbor"):
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
) -> str | None:
    """Return a user-facing fallback when synthesis should be skipped, else None."""
    semantic_evidence = [chunk for chunk in evidence if chunk.get("from_semantic_search")]
    if semantic_evidence:
        scores = _semantic_primary_scores(evidence)
        if scores and max(scores) < _min_relevance_score(settings):
            return low_relevance_message(lang)
        return None

    if not evidence:
        return not_found_message(lang)

    return None


class RAGService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.embedding = EmbeddingService(self.settings)
        self.vector_store = VectorStore(self.settings)
        self.fulltext_store = (
            FulltextStore(self.settings) if self.settings.hybrid_enabled else None
        )
        self.reranker = None
        if self.settings.rerank_enabled:
            if model_path_ready(self.settings.rerank_model):
                self.reranker = RerankerService(self.settings)
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
            select(ChunkAsset).where(ChunkAsset.chunk_id.in_(chunk_uuids))
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
            asset_captions = [asset.caption for asset in chunk_assets if asset.caption]
            body_text = format_context_body(
                chunk.text,
                caption=chunk.caption,
                asset_captions=asset_captions,
            )
            index_text = chunk_rerank_text(
                chunk.text,
                caption=chunk.caption,
                asset_captions=asset_captions,
            )
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": str(document.id),
                    "document_name": document.name,
                    "page": chunk.page,
                    "section": chunk.section,
                    "chunk_type": chunk.chunk_type,
                    "content_role": chunk.content_role,
                    "chunk_index": chunk.chunk_index,
                    "caption": chunk.caption,
                    "score": score_map.get(chunk_id, 0.0),
                    "snippet": chunk_display_snippet(
                        chunk.text,
                        caption=chunk.caption,
                        asset_captions=asset_captions,
                    ),
                    "text": body_text,
                    "index_text": index_text,
                    "is_neighbor": False,
                    "assets": [
                        {
                            "asset_id": str(asset.id),
                            "type": asset.asset_type,
                            "page": asset.page,
                            "url": asset_url(asset.id),
                            "object_key": asset.object_key,
                            "caption": asset.caption,
                        }
                        for asset in chunk_assets
                    ],
                }
            )
        return chunks

    async def _expand_neighbor_chunks(
        self,
        db: AsyncSession,
        chunks: list[dict],
    ) -> list[dict]:
        window = self.settings.rag_neighbor_window
        if window <= 0 or not chunks:
            return chunks

        hit_pairs: list[tuple[UUID, int]] = []
        for chunk in chunks:
            document_id = chunk.get("document_id")
            chunk_index = chunk.get("chunk_index")
            if document_id is None or chunk_index is None:
                continue
            hit_pairs.append((UUID(str(document_id)), int(chunk_index)))
        if not hit_pairs:
            return chunks

        document_ids = {doc_id for doc_id, _ in hit_pairs}
        result = await db.execute(
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.document_id.in_(document_ids))
        )
        by_document: dict[str, dict[int, tuple[Chunk, Document]]] = {}
        for chunk, document in result.all():
            doc_key = str(document.id)
            by_document.setdefault(doc_key, {})[chunk.chunk_index] = (chunk, document)

        existing_ids = {chunk["chunk_id"] for chunk in chunks}
        neighbor_ids: list[str] = []
        for document_id, hit_index in hit_pairs:
            doc_chunks = by_document.get(str(document_id), {})
            for neighbor_index in range(hit_index - window, hit_index + window + 1):
                if neighbor_index == hit_index:
                    continue
                row = doc_chunks.get(neighbor_index)
                if row is None:
                    continue
                neighbor_id = str(row[0].id)
                if neighbor_id in existing_ids:
                    continue
                existing_ids.add(neighbor_id)
                neighbor_ids.append(neighbor_id)

        if not neighbor_ids:
            return self._sort_chunks_for_context(chunks)

        neighbor_score_map = {chunk_id: 0.0 for chunk_id in neighbor_ids}
        neighbor_chunks = await self._load_chunks(db, neighbor_ids, neighbor_score_map)
        for chunk in neighbor_chunks:
            chunk["is_neighbor"] = True

        return self._sort_chunks_for_context(chunks + neighbor_chunks)

    @staticmethod
    def _sort_chunks_for_context(chunks: list[dict]) -> list[dict]:
        return sorted(
            chunks,
            key=lambda item: (
                item.get("document_id") or "",
                item.get("chunk_index") if item.get("chunk_index") is not None else -1,
                1 if item.get("is_neighbor") else 0,
            ),
        )

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

        chunks = await self._load_chunks(db, ranked_chunk_ids, score_map)
        chunks = filter_chunks(chunks, chunk_filter)
        if not chunks:
            return []

        if self.reranker:
            chunks = self.reranker.rerank(question, chunks)
        primary = chunks[:final_k]
        if self.settings.rag_neighbor_window > 0:
            primary = await self._expand_neighbor_chunks(db, primary)
        return primary

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
        broad_chunks, strict_chunks = await asyncio.gather(
            self._retrieve_once(db, question, broad_filter, query_vector=query_vector),
            self._retrieve_once(db, question, chunk_filter, query_vector=query_vector),
        )

        if strict_chunks:
            if broad_chunks and broad_filter.model_dump_json() != chunk_filter.model_dump_json():
                logger.info(
                    "Metadata filter applied; strict=%s",
                    chunk_filter.model_dump(exclude_none=True),
                )
            return strict_chunks

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
    ) -> list[dict]:
        if chunk_filter.has_metadata_constraints():
            return await self._retrieve_with_relaxation(db, question, chunk_filter)
        return await self._retrieve_once(db, question, chunk_filter, top_k=top_k) or []

    async def read_chunks(
        self,
        db: AsyncSession,
        chunk_ids: list[str],
    ) -> list[dict]:
        score_map = {chunk_id: 1.0 for chunk_id in chunk_ids}
        return await self._load_chunks(db, chunk_ids, score_map)

    def build_context(self, chunks: list[dict]) -> str:
        parts: list[str] = []
        for index, item in enumerate(chunks, start=1):
            header = f"[{index}] {item['document_name']}"
            chunk_type = item.get("chunk_type")
            if chunk_type and chunk_type != "text":
                header += f" type={chunk_type}"
            if item.get("page"):
                header += f" p.{item['page']}"
            if item.get("section"):
                header += f" §{item['section']}"
            if item.get("is_neighbor"):
                header += " (上下文)"
            if item.get("assets"):
                header += " (visual)"
            parts.append(f"{header}\n{item['text']}")
        return "\n\n---\n\n".join(parts)
