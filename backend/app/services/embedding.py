from threading import Lock

from FlagEmbedding.bge_m3 import BGEM3FlagModel

from app.config import Settings, get_settings

_lock = Lock()
_model: BGEM3FlagModel | None = None


def _get_model(settings: Settings) -> BGEM3FlagModel:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = BGEM3FlagModel(
                    settings.embedding_model,
                    use_fp16=settings.embedding_device != "cpu",
                    device=settings.embedding_device,
                )
    return _model


class EmbeddingService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = _get_model(self.settings)
        output = model.encode(
            texts,
            batch_size=self.settings.embedding_batch_size,
            max_length=8192,
        )
        dense = output["dense_vecs"]
        return [vec.tolist() for vec in dense]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_queries([text])[0]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = _get_model(self.settings)
        output = model.encode(
            texts,
            batch_size=min(self.settings.embedding_batch_size, len(texts)),
            max_length=8192,
        )
        dense = output["dense_vecs"]
        return [vec.tolist() for vec in dense]
