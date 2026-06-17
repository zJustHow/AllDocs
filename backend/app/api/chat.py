import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ChatRequest
from app.config import get_settings
from app.db.models import Message, Session
from app.db.session import get_db
from app.services.agent.answer_flow import persist_turn, stream_agent_answer
from app.services.deps import get_agent_service
from app.services.rag import detect_language

router = APIRouter(prefix="/chat", tags=["chat"])


async def _get_or_create_session(
    db: AsyncSession,
    session_id: uuid.UUID | None,
    doc_ids: list[uuid.UUID],
) -> Session:
    if session_id:
        session = await db.get(Session, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    session = Session(doc_ids=[str(doc_id) for doc_id in doc_ids])
    db.add(session)
    await db.flush()
    return session


STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    session = await _get_or_create_session(db, payload.session_id, payload.doc_ids)
    await db.commit()
    history_result = await db.execute(
        select(Message).where(Message.session_id == session.id).order_by(Message.created_at)
    )
    history = [
        {"role": message.role, "content": message.content}
        for message in history_result.scalars().all()
    ]

    doc_ids = payload.doc_ids or [uuid.UUID(doc_id) for doc_id in session.doc_ids]
    chunk_filters = payload.filters
    lang = detect_language(payload.message)
    agent = get_agent_service()

    async def event_stream():
        try:
            async for event in stream_agent_answer(
                agent,
                db,
                payload.message,
                doc_ids or None,
                chunk_filters,
                history,
                settings,
                lang,
            ):
                event_type = event["type"]
                if event_type == "fallback":
                    content = event["content"]
                    yield _sse({"type": "delta", "content": content})
                    yield _sse(
                        {
                            "type": "done",
                            "session_id": str(session.id),
                            "citations": [],
                            "language": event["language"],
                        }
                    )
                    await persist_turn(db, session.id, payload.message, content, [])
                    return

                if event_type == "citations":
                    yield _sse({"type": "citations", "citations": event["citations"]})
                    continue

                if event_type == "delta":
                    yield _sse({"type": "delta", "content": event["content"]})
                    continue

                if event_type == "embeds":
                    yield _sse({"type": "embeds", "embeds": event["embeds"]})
                    continue

                if event_type == "complete":
                    yield _sse(
                        {
                            "type": "done",
                            "session_id": str(session.id),
                            "content": event["answer"],
                            "citations": event["citations"],
                            "embeds": event["embeds"],
                            "language": event["language"],
                        }
                    )
                    await persist_turn(
                        db,
                        session.id,
                        payload.message,
                        event["answer"],
                        event["citations"],
                        event["embeds"],
                    )
                    return

                yield _sse(event)
        except Exception as exc:
            await db.rollback()
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
