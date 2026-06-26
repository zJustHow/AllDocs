import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.api import admin, assets, auth, chat, documents, settings, ws_voice
from app.db.session import async_session_factory, init_db
from app.config import get_settings
from app.observability import (
    RequestObservabilityMiddleware,
    configure_logging,
    metrics_payload,
)
from app.services.infra_init import ensure_external_stores_async
from app.services.runtime_settings import refresh_from_session
from app.services.speech import is_whisper_ready, warm_whisper

logger = logging.getLogger(__name__)
configure_logging(get_settings().log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    async with async_session_factory() as db:
        await db.run_sync(refresh_from_session)
    await ensure_external_stores_async()

    async def _warm_whisper() -> None:
        try:
            await asyncio.to_thread(warm_whisper)
            logger.info("Whisper speech model ready")
        except Exception:
            logger.exception("Failed to preload Whisper speech model")

    asyncio.create_task(_warm_whisper())
    yield


app = FastAPI(
    title="AllDocs",
    description="RAG-based operation guide Q&A: local embedding, LLM API, local speech",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestObservabilityMiddleware)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin.users_router, prefix="/api/v1")
app.include_router(admin.audit_router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(assets.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(ws_voice.router)


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {"status": "ok", "speech_ready": is_whisper_ready()}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    if not get_settings().metrics_enabled:
        return Response(status_code=404)
    payload, content_type = metrics_payload()
    return Response(content=payload, headers={"Content-Type": content_type})
