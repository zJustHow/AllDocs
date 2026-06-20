import httpx

from app.config import Settings, get_settings


class InferenceClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        base = self.settings.inference_url.rstrip("/")
        self._base_url = base
        self._timeout = self.settings.inference_timeout_seconds
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def _client(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._sync_client

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
            )
        return self._async_client

    def close(self) -> None:
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None

    async def aclose(self) -> None:
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    def embed_queries_sync(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client().post("/v1/embed/queries", json={"texts": texts})
        response.raise_for_status()
        return response.json()["vectors"]

    def embed_documents_sync(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client().post("/v1/embed/documents", json={"texts": texts})
        response.raise_for_status()
        return response.json()["vectors"]

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._get_async_client().post(
            "/v1/embed/queries",
            json={"texts": texts},
        )
        response.raise_for_status()
        return response.json()["vectors"]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._get_async_client().post(
            "/v1/embed/documents",
            json={"texts": texts},
        )
        response.raise_for_status()
        return response.json()["vectors"]

    def rerank_sync(
        self,
        query: str,
        items: list[dict],
        *,
        top_k: int | None = None,
    ) -> list[dict]:
        if not items:
            return []
        passages = [
            {
                "text": item["text"],
                "index_text": item.get("index_text") or item["text"],
            }
            for item in items
        ]
        payload: dict = {"query": query, "passages": passages}
        if top_k is not None:
            payload["top_k"] = top_k
        response = self._client().post("/v1/rerank", json=payload)
        response.raise_for_status()
        ranked = response.json()["items"]
        return self._merge_rerank_results(items, ranked, top_k)

    async def rerank(
        self,
        query: str,
        items: list[dict],
        *,
        top_k: int | None = None,
    ) -> list[dict]:
        if not items:
            return []
        passages = [
            {
                "text": item["text"],
                "index_text": item.get("index_text") or item["text"],
            }
            for item in items
        ]
        payload: dict = {"query": query, "passages": passages}
        if top_k is not None:
            payload["top_k"] = top_k
        response = await self._get_async_client().post("/v1/rerank", json=payload)
        response.raise_for_status()
        ranked = response.json()["items"]
        return self._merge_rerank_results(items, ranked, top_k)

    @staticmethod
    def _merge_rerank_results(
        items: list[dict],
        ranked: list[dict],
        top_k: int | None,
    ) -> list[dict]:
        merged: list[dict] = []
        for entry in ranked:
            item = dict(items[int(entry["index"])])
            item["score"] = float(entry["score"])
            merged.append(item)
        if top_k is not None:
            return merged[:top_k]
        return merged
