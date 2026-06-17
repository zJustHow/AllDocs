import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.config import get_settings
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


app = FastAPI(
    title="AllDocs Inference",
    description="Dedicated BGE-M3 embedding and rerank service",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    if not hasattr(app.state, "engine"):
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return {"status": "ready"}


@app.post("/v1/embed/queries", response_model=EmbedResponse)
async def embed_queries(payload: EmbedRequest) -> EmbedResponse:
    vectors = await app.state.batcher.embed(payload.texts)
    return EmbedResponse(vectors=vectors)


@app.post("/v1/embed/documents", response_model=EmbedResponse)
async def embed_documents(payload: EmbedRequest) -> EmbedResponse:
    vectors = await app.state.batcher.embed(payload.texts)
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
    ranked = await asyncio.to_thread(
        engine.rerank, payload.query, items, top_k=payload.top_k
    )
    response_items = [
        RerankItem(index=int(item["_index"]), score=float(item["score"]))
        for item in ranked
    ]
    return RerankResponse(items=response_items)
