from functools import lru_cache
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import Settings, get_settings

VECTOR_SIZE = 1024


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url)


class VectorStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = get_qdrant_client()
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        collections = {c.name for c in self.client.get_collections().collections}
        if self.settings.qdrant_collection not in collections:
            self.client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=qmodels.VectorParams(size=VECTOR_SIZE, distance=qmodels.Distance.COSINE),
            )

    def upsert_chunks(
        self,
        chunk_ids: list[UUID],
        vectors: list[list[float]],
        payloads: list[dict],
    ) -> None:
        points = [
            qmodels.PointStruct(
                id=str(chunk_id),
                vector=vector,
                payload=payload,
            )
            for chunk_id, vector, payload in zip(chunk_ids, vectors, payloads, strict=True)
        ]
        self.client.upsert(collection_name=self.settings.qdrant_collection, points=points)

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        doc_ids: list[UUID] | None = None,
    ) -> list[qmodels.ScoredPoint]:
        query_filter = None
        if doc_ids:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="document_id",
                        match=qmodels.MatchAny(any=[str(doc_id) for doc_id in doc_ids]),
                    )
                ]
            )
        return self.client.search(
            collection_name=self.settings.qdrant_collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )

    def delete_by_document(self, document_id: UUID) -> None:
        self.client.delete(
            collection_name=self.settings.qdrant_collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=str(document_id)),
                        )
                    ]
                )
            ),
        )
