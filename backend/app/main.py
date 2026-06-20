import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assets, chat, documents, settings, ws_voice
from app.db.session import async_session_factory, init_db
from app.services.infra_init import ensure_external_stores_async
from app.services.runtime_settings import refresh_from_session
from app.services.speech import is_whisper_ready, warm_whisper

logger = logging.getLogger(__name__)


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

app.include_router(documents.router, prefix="/api/v1")
app.include_router(assets.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(ws_voice.router)


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {"status": "ok", "speech_ready": is_whisper_ready()}
