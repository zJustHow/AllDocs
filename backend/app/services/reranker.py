from threading import Lock

from FlagEmbedding import FlagReranker

from app.config import Settings, get_settings

_lock = Lock()
_model: FlagReranker | None = None


def _get_model(settings: Settings) -> FlagReranker:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = FlagReranker(
                    settings.rerank_model,
                    use_fp16=settings.rerank_device != "cpu",
                )
    return _model


class RerankerService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def rerank(self, question: str, items: list[dict]) -> list[dict]:
        if not items:
            return []

        pairs = [[question, item.get("index_text") or item["text"]] for item in items]
        model = _get_model(self.settings)
        scores = model.compute_score(
            pairs,
            batch_size=self.settings.rerank_batch_size,
            max_length=8192,
        )
        if not isinstance(scores, list):
            scores = [scores]

        ranked = []
        for item, score in zip(items, scores, strict=True):
            ranked.append(
                {
                    **item,
                    "vector_score": item.get("score"),
                    "score": float(score),
                }
            )
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[: self.settings.rag_top_k]
