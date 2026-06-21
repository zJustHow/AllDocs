from app.config import Settings, get_settings
from app.services.inference_client import InferenceClient


class LocalEmbeddingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._local = None

    def _service(self):
        if self._local is None:
            from app.services.embedding import EmbeddingService

            self._local = EmbeddingService(self.settings)
        return self._local

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._service().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._service().embed_query(text)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._service().embed_queries(texts)

    async def embed_queries_async(self, texts: list[str]) -> list[list[float]]:
        import asyncio

        return await asyncio.to_thread(self.embed_queries, texts)

    async def embed_query_async(self, text: str) -> list[float]:
        vectors = await self.embed_queries_async([text])
        return vectors[0]


class RemoteEmbeddingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = InferenceClient(self.settings)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batch_size = self.settings.embedding_batch_size
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            vectors.extend(
                self._client.embed_documents_sync(texts[start : start + batch_size])
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_queries([text])[0]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_queries_sync(texts)

    async def embed_queries_async(self, texts: list[str]) -> list[list[float]]:
        return await self._client.embed_queries(texts)

    async def embed_query_async(self, text: str) -> list[float]:
        vectors = await self.embed_queries_async([text])
        return vectors[0]


def get_embedding_service(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.inference_url:
        return RemoteEmbeddingService(settings)
    return LocalEmbeddingService(settings)
