from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
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


class VoiceQueryResponse(BaseModel):
    session_id: UUID
    transcript: str
    answer: str
    citations: list[Citation]
    language: str
    audio_base64: str | None = None


class TranscribeResponse(BaseModel):
    text: str
    language: str
    duration: float | None = None
