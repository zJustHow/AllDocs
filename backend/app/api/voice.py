import base64
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TranscribeResponse, VoiceQueryResponse
from app.db.models import Message, Session
from app.db.session import get_db
from app.services.rag import RAGService
from app.services.speech import SpeechService

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> TranscribeResponse:
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    speech = SpeechService()
    result = speech.transcribe(audio_bytes, language=language)
    return TranscribeResponse(
        text=result["text"],
        language=result["language"],
        duration=result.get("duration"),
    )


@router.post("/query", response_model=VoiceQueryResponse)
async def voice_query(
    file: UploadFile = File(...),
    session_id: uuid.UUID | None = Form(default=None),
    doc_ids: str = Form(default=""),
    with_audio: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
) -> VoiceQueryResponse:
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    speech = SpeechService()
    transcription = speech.transcribe(audio_bytes)
    question = transcription["text"]
    if not question:
        raise HTTPException(status_code=400, detail="Could not transcribe audio")

    parsed_doc_ids = [uuid.UUID(item.strip()) for item in doc_ids.split(",") if item.strip()]

    if session_id:
        session = await db.get(Session, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = Session(doc_ids=[str(doc_id) for doc_id in parsed_doc_ids])
        db.add(session)
        await db.flush()

    history_result = await db.execute(
        select(Message).where(Message.session_id == session.id).order_by(Message.created_at)
    )
    history = [
        {"role": message.role, "content": message.content}
        for message in history_result.scalars().all()
    ]

    effective_doc_ids = parsed_doc_ids or [uuid.UUID(doc_id) for doc_id in session.doc_ids]
    rag = RAGService()
    answer, citations, lang = await rag.answer(
        db,
        question,
        effective_doc_ids or None,
        history,
    )

    db.add(Message(session_id=session.id, role="user", content=question))
    db.add(
        Message(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=citations,
        )
    )
    await db.commit()

    audio_base64 = None
    if with_audio:
        audio_wav = speech.synthesize(answer, lang=lang)
        audio_base64 = base64.b64encode(audio_wav).decode("ascii")

    return VoiceQueryResponse(
        session_id=session.id,
        transcript=question,
        answer=answer,
        citations=citations,
        language=lang,
        audio_base64=audio_base64,
    )
