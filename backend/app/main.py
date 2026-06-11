from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, documents, voice, ws_voice
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="AllDocs",
    description="RAG-based manual Q&A: local embedding, LLM API, local speech",
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
app.include_router(chat.router, prefix="/api/v1")
app.include_router(voice.router, prefix="/api/v1")
app.include_router(ws_voice.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
