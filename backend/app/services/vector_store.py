from functools import lru_cache
from threading import Lock
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import Settings, get_settings
from app.services.chunk_filter import ChunkFilter, build_qdrant_filter

VECTOR_SIZE = 1024

_collection_lock = Lock()
_collection_ready = False


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url)


def ensure_collection(settings: Settings | None = None) -> None:
    global _collection_ready
    if _collection_ready:
        return
    with _collection_lock:
        if _collection_ready:
            return
        settings = settings or get_settings()
        client = get_qdrant_client()
        collections = {c.name for c in client.get_collections().collections}
        if settings.qdrant_collection not in collections:
            client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=qmodels.VectorParams(
                    size=VECTOR_SIZE, distance=qmodels.Distance.COSINE
                ),
            )
        _collection_ready = True


class VectorStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = get_qdrant_client()

    def upsert_chunks(
        self,
        chunk_ids: list[UUID],
        vectors: list[list[float]],
        payloads: list[dict],
    ) -> None:
        ensure_collection(self.settings)
        batch_size = max(1, self.settings.qdrant_upsert_batch_size)
        for start in range(0, len(chunk_ids), batch_size):
            batch_ids = chunk_ids[start : start + batch_size]
            batch_vectors = vectors[start : start + batch_size]
            batch_payloads = payloads[start : start + batch_size]
            points = [
                qmodels.PointStruct(
                    id=str(chunk_id),
                    vector=vector,
                    payload=payload,
                )
                for chunk_id, vector, payload in zip(
                    batch_ids, batch_vectors, batch_payloads, strict=True
                )
            ]
            self.client.upsert(
                collection_name=self.settings.qdrant_collection,
                points=points,
            )

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        chunk_filter: ChunkFilter | None = None,
    ) -> list[qmodels.ScoredPoint]:
        ensure_collection(self.settings)
        query_filter = build_qdrant_filter(chunk_filter)
        return self.client.search(
            collection_name=self.settings.qdrant_collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )

    def delete_by_document(self, document_id: UUID) -> None:
        ensure_collection(self.settings)
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
