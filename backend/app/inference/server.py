import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from app.config import get_settings
from app.observability import (
    RequestObservabilityMiddleware,
    configure_logging,
    metrics_payload,
    timed_stage,
)
from app.inference.batcher import EmbedBatcher
from app.inference.engine import InferenceEngine
from app.inference.schemas import (
    EmbedRequest,
    EmbedResponse,
    RerankRequest,
    RerankResponse,
    RerankItem,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = InferenceEngine(settings)
    batcher = EmbedBatcher(
        engine.embed_queries,
        max_wait_s=settings.inference_batch_wait_ms / 1000.0,
        max_batch_texts=settings.inference_batch_max_texts,
    )
    await batcher.start()
    app.state.engine = engine
    app.state.batcher = batcher
    yield
    await batcher.stop()


settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="AllDocs Inference",
    description="Dedicated BGE-M3 embedding and rerank service",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(RequestObservabilityMiddleware)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    if not hasattr(app.state, "engine"):
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    if not settings.metrics_enabled:
        return Response(status_code=404)
    payload, content_type = metrics_payload()
    return Response(content=payload, headers={"Content-Type": content_type})


async def _embed_batched(batcher: EmbedBatcher, texts: list[str], *, chunk_size: int) -> list[list[float]]:
    """Chunk large embed requests so retrieval queries can interleave between batches."""
    if not texts:
        return []
    if len(texts) <= chunk_size:
        return await batcher.embed(texts)

    vectors: list[list[float]] = []
    for start in range(0, len(texts), chunk_size):
        vectors.extend(await batcher.embed(texts[start : start + chunk_size]))
    return vectors


@app.post("/v1/embed/queries", response_model=EmbedResponse)
async def embed_queries(payload: EmbedRequest) -> EmbedResponse:
    settings = get_settings()
    chunk_size = min(settings.embedding_batch_size, settings.inference_batch_max_texts)
    with timed_stage("inference", "embed_queries", text_count=len(payload.texts)):
        vectors = await _embed_batched(app.state.batcher, payload.texts, chunk_size=chunk_size)
    return EmbedResponse(vectors=vectors)


@app.post("/v1/embed/documents", response_model=EmbedResponse)
async def embed_documents(payload: EmbedRequest) -> EmbedResponse:
    settings = get_settings()
    chunk_size = min(settings.embedding_batch_size, settings.inference_batch_max_texts)
    with timed_stage("inference", "embed_documents", text_count=len(payload.texts)):
        vectors = await _embed_batched(app.state.batcher, payload.texts, chunk_size=chunk_size)
    return EmbedResponse(vectors=vectors)


@app.post("/v1/rerank", response_model=RerankResponse)
async def rerank(payload: RerankRequest) -> RerankResponse:
    engine: InferenceEngine = app.state.engine
    items = [
        {
            "text": passage.text,
            "index_text": passage.index_text or passage.text,
            "_index": idx,
        }
        for idx, passage in enumerate(payload.passages)
    ]
    with timed_stage("inference", "rerank", passage_count=len(items)):
        ranked = await asyncio.to_thread(
            engine.rerank, payload.query, items, top_k=payload.top_k
        )
    response_items = [
        RerankItem(index=int(item["_index"]), score=float(item["score"]))
        for item in ranked
    ]
    return RerankResponse(items=response_items)
