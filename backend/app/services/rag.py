from uuid import UUID

from langdetect import DetectorFactory, detect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Chunk, Document
from app.services.embedding import EmbeddingService
from app.services.fulltext_store import FulltextStore
from app.services.hybrid import reciprocal_rank_fusion
from app.services.llm import LLMService
from app.services.reranker import RerankerService
from app.services.vector_store import VectorStore

DetectorFactory.seed = 0


def detect_language(text: str) -> str:
    try:
        lang = detect(text)
        return "zh" if lang.startswith("zh") else "en" if lang == "en" else lang
    except Exception:
        return "zh"


class RAGService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.embedding = EmbeddingService(self.settings)
        self.vector_store = VectorStore(self.settings)
        self.fulltext_store = (
            FulltextStore(self.settings) if self.settings.hybrid_enabled else None
        )
        self.llm = LLMService(self.settings)
        self.reranker = RerankerService(self.settings) if self.settings.rerank_enabled else None

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
                    "score": score_map.get(chunk_id, 0.0),
                    "snippet": chunk.text[:300],
                    "text": chunk.text,
                }
            )
        return citations

    async def retrieve(
        self,
        db: AsyncSession,
        question: str,
        doc_ids: list[UUID] | None = None,
    ) -> list[dict]:
        use_extended_retrieval = self.reranker or self.settings.hybrid_enabled
        retrieve_k = self.settings.rag_retrieve_k if use_extended_retrieval else self.settings.rag_top_k

        query_vector = self.embedding.embed_query(question)
        vector_hits = self.vector_store.search(
            query_vector=query_vector,
            top_k=retrieve_k,
            doc_ids=doc_ids,
        )
        vector_ids = [str(hit.id) for hit in vector_hits]
        vector_score_map = {str(hit.id): float(hit.score) for hit in vector_hits}

        if self.fulltext_store:
            bm25_hits = self.fulltext_store.search(question, retrieve_k, doc_ids)
            bm25_ids = [chunk_id for chunk_id, _ in bm25_hits]
            fused = reciprocal_rank_fusion(
                [vector_ids, bm25_ids],
                top_k=retrieve_k,
                k=self.settings.hybrid_rrf_k,
            )
            ranked_chunk_ids = [chunk_id for chunk_id, _ in fused]
            score_map = {chunk_id: score for chunk_id, score in fused}
        else:
            ranked_chunk_ids = vector_ids
            score_map = vector_score_map

        citations = await self._load_citations(db, ranked_chunk_ids, score_map)
        if not citations:
            return []

        if self.reranker:
            citations = self.reranker.rerank(question, citations)
        else:
            citations = citations[: self.settings.rag_top_k]

        return citations

    def build_context(self, citations: list[dict]) -> str:
        parts: list[str] = []
        for index, item in enumerate(citations, start=1):
            header = f"[{index}] {item['document_name']}"
            if item.get("page"):
                header += f" p.{item['page']}"
            if item.get("section"):
                header += f" §{item['section']}"
            parts.append(f"{header}\n{item['text']}")
        return "\n\n---\n\n".join(parts)

    async def answer(
        self,
        db: AsyncSession,
        question: str,
        doc_ids: list[UUID] | None = None,
        chat_history: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[dict], str]:
        citations = await self.retrieve(db, question, doc_ids)
        lang = detect_language(question)
        if not citations:
            if lang == "en":
                return "Not found in the manual.", [], lang
            return "说明书中未找到相关信息。", [], lang

        context = self.build_context(citations)
        answer = await self.llm.chat(question, context, chat_history)
        public_citations = [
            {
                "document_id": item["document_id"],
                "document_name": item["document_name"],
                "page": item["page"],
                "section": item["section"],
                "snippet": item["snippet"],
                "score": item["score"],
            }
            for item in citations
        ]
        return answer, public_citations, lang
