import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ChatRequest, ChatResponse
from app.config import get_settings
from app.db.models import Message, Session
from app.db.session import get_db
from app.services.agent import AgentRAGService
from app.services.citations_util import finalize_answer, public_citations
from app.services.rag import detect_language
from app.services.vision_util import prepare_vision_images

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

    if payload.stream:
        lang = detect_language(payload.message)

        async def event_stream():
            try:
                yield f"data: {json.dumps({'type': 'status', 'stage': 'agent'}, ensure_ascii=False)}\n\n"
                agent = AgentRAGService(settings)
                step_events: list[dict] = []

                async def on_step(event: dict) -> None:
                    step_events.append(event)

                result = await agent.run(
                    db,
                    payload.message,
                    doc_ids or None,
                    chunk_filters,
                    history,
                    on_step=on_step,
                    skip_synthesis=True,
                )
                for event in step_events:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                if result.fallback_message:
                    fallback = result.fallback_message
                    yield f"data: {json.dumps({'type': 'delta', 'content': fallback}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'session_id': str(session.id), 'citations': [], 'language': lang}, ensure_ascii=False)}\n\n"
                    db.add(Message(session_id=session.id, role="user", content=payload.message))
                    db.add(
                        Message(
                            session_id=session.id,
                            role="assistant",
                            content=fallback,
                            citations=[],
                        )
                    )
                    await db.commit()
                    return

                refs = public_citations(result.evidence)
                yield f"data: {json.dumps({'type': 'citations', 'citations': refs}, ensure_ascii=False)}\n\n"

                vision_images = await prepare_vision_images(db, result.evidence, settings)
                answer_parts: list[str] = []
                async for delta in agent.iter_synthesis(
                    payload.message, result.evidence, history, vision_images
                ):
                    answer_parts.append(delta)
                    yield f"data: {json.dumps({'type': 'delta', 'content': delta}, ensure_ascii=False)}\n\n"

                answer, refs, embeds = finalize_answer("".join(answer_parts), result.evidence)
                if embeds:
                    yield f"data: {json.dumps({'type': 'embeds', 'embeds': embeds}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'session_id': str(session.id), 'content': answer, 'citations': refs, 'embeds': embeds, 'language': lang}, ensure_ascii=False)}\n\n"
                db.add(Message(session_id=session.id, role="user", content=payload.message))
                db.add(
                    Message(
                        session_id=session.id,
                        role="assistant",
                        content=answer,
                        citations=refs,
                        embeds=embeds,
                    )
                )
                await db.commit()
            except Exception as exc:
                await db.rollback()
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
        )

    agent = AgentRAGService(settings)
    result = await agent.run(
        db,
        payload.message,
        doc_ids or None,
        chunk_filters,
        history,
    )
    db.add(Message(session_id=session.id, role="user", content=payload.message))
    db.add(
        Message(
            session_id=session.id,
            role="assistant",
            content=result.answer,
            citations=result.citations,
            embeds=result.embeds,
        )
    )
    await db.commit()

    return ChatResponse(
        session_id=session.id,
        answer=result.answer,
        citations=result.citations,
        embeds=result.embeds,
        language=result.language,
    )
