from threading import Lock

from app.config import Settings, get_settings
from app.services.embedding import EmbeddingService
from app.services.reranker import RerankerService


class InferenceEngine:
    """Single-process GPU/CPU inference with serialized model access."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._embedding = EmbeddingService(self.settings)
        self._reranker = (
            RerankerService(self.settings) if self.settings.rerank_enabled else None
        )
        self._lock = Lock()

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            return self._embedding.embed_queries(texts)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batch_size = self.settings.embedding_batch_size
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            with self._lock:
                vectors.extend(
                    self._embedding.embed_documents(texts[start : start + batch_size])
                )
        return vectors

    def rerank(
        self,
        query: str,
        items: list[dict],
        *,
        top_k: int | None = None,
    ) -> list[dict]:
        if not items:
            return []
        if self._reranker is None:
            return items[: top_k or self.settings.rag_top_k]

        with self._lock:
            ranked = self._reranker.rerank(query, items)
        if top_k is not None:
            return ranked[:top_k]
        return ranked
