from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assets, chat, documents, ws_voice
from app.db.session import init_db
from app.services.infra_init import ensure_external_stores_async


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await ensure_external_stores_async()
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
app.include_router(ws_voice.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
