import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.auth_deps import get_current_user
from app.api.schemas import ChatRequest
from app.config import get_settings
from app.db.models import Message, User
from app.db.session import async_session_factory
from app.services.agent.answer_flow import persist_turn, stream_agent_answer
from app.services.chat_sessions import get_or_create_chat_session
from app.services.deps import get_agent_service
from app.services.rag import detect_language

router = APIRouter(prefix="/chat", tags=["chat"])


STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(payload: ChatRequest, user: User = Depends(get_current_user)):
    settings = get_settings()
    async with async_session_factory() as db:
        session, doc_ids = await get_or_create_chat_session(
            db,
            user=user,
            session_id=payload.session_id,
            requested_doc_ids=payload.doc_ids,
        )
        await db.commit()
        session_id = session.id
        history_result = await db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
        history = [
            {"role": message.role, "content": message.content}
            for message in history_result.scalars().all()
        ]

    chunk_filters = payload.filters
    lang = detect_language(payload.message)
    agent = get_agent_service()

    async def event_stream():
        try:
            async for event in stream_agent_answer(
                agent,
                payload.message,
                doc_ids or None,
                chunk_filters,
                history,
                settings,
                lang,
            ):
                event_type = event["type"]
                if event_type == "clarify":
                    content = event["content"]
                    yield _sse({"type": "delta", "content": content})
                    yield _sse(
                        {
                            "type": "done",
                            "session_id": str(session_id),
                            "citations": [],
                            "language": event["language"],
                        }
                    )
                    async with async_session_factory() as persist_db:
                        await persist_turn(persist_db, session_id, payload.message, content, [])
                    return

                if event_type == "fallback":
                    content = event["content"]
                    yield _sse({"type": "delta", "content": content})
                    yield _sse(
                        {
                            "type": "done",
                            "session_id": str(session_id),
                            "citations": [],
                            "language": event["language"],
                        }
                    )
                    async with async_session_factory() as persist_db:
                        await persist_turn(persist_db, session_id, payload.message, content, [])
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
                            "session_id": str(session_id),
                            "content": event["answer"],
                            "citations": event["citations"],
                            "embeds": event["embeds"],
                            "language": event["language"],
                        }
                    )
                    async with async_session_factory() as persist_db:
                        await persist_turn(
                            persist_db,
                            session_id,
                            payload.message,
                            event["answer"],
                            event["citations"],
                            event["embeds"],
                        )
                    return

                yield _sse(event)
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
