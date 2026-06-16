from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.chunk_filter import ChunkFilter

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ChunkFilter",
    "Citation",
    "DocumentResponse",
]


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    content_type: str = "application/pdf"
    status: str
    page_count: int | None
    ocr_pages: int | None = 0
    progress: int = 0
    progress_message: str | None = None
    error_message: str | None
    created_at: datetime


class ChatRequest(BaseModel):
    message: str
    session_id: UUID | None = None
    doc_ids: list[UUID] = Field(default_factory=list)
    filters: ChunkFilter | None = None
    stream: bool = False


class Citation(BaseModel):
    document_id: str
    document_name: str
    page: int | None
    section: str | None
    snippet: str
    score: float | None = None


class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    citations: list[Citation]
    language: str

