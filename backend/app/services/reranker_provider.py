from app.config import Settings, get_settings
from app.services.inference_client import InferenceClient


class LocalRerankerService:
    def __init__(self, settings: Settings | None = None) -> None:
        from app.services.reranker import RerankerService

        self._local = RerankerService(settings)
        self.settings = settings or get_settings()

    def rerank(self, question: str, items: list[dict]) -> list[dict]:
        return self._local.rerank(question, items)

    async def rerank_async(self, question: str, items: list[dict]) -> list[dict]:
        import asyncio

        return await asyncio.to_thread(self.rerank, question, items)


class RemoteRerankerService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = InferenceClient(self.settings)

    def rerank(self, question: str, items: list[dict]) -> list[dict]:
        return self._client.rerank_sync(
            question,
            items,
            top_k=self.settings.rag_top_k,
        )

    async def rerank_async(self, question: str, items: list[dict]) -> list[dict]:
        return await self._client.rerank(
            question,
            items,
            top_k=self.settings.rag_top_k,
        )


def get_reranker_service(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.inference_url:
        return RemoteRerankerService(settings)
    return LocalRerankerService(settings)
