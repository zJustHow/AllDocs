import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ChatRequest, ChatResponse
from app.db.models import Message, Session
from app.db.session import get_db
from app.services.rag import RAGService, detect_language

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
    session = await _get_or_create_session(db, payload.session_id, payload.doc_ids)
    await db.commit()
    history_result = await db.execute(
        select(Message).where(Message.session_id == session.id).order_by(Message.created_at)
    )
    history = [
        {"role": message.role, "content": message.content}
        for message in history_result.scalars().all()
    ]

    rag = RAGService()
    doc_ids = payload.doc_ids or [uuid.UUID(doc_id) for doc_id in session.doc_ids]

    if payload.stream:
        citations = await rag.retrieve(db, payload.message, doc_ids or None)
        lang = detect_language(payload.message)

        async def event_stream():
            try:
                if not citations:
                    fallback = (
                        "Not found in the manual."
                        if lang == "en"
                        else "说明书中未找到相关信息。"
                    )
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

                context = rag.build_context(citations)
                answer_parts: list[str] = []
                async for delta in rag.llm.chat_stream(payload.message, context, history):
                    answer_parts.append(delta)
                    yield f"data: {json.dumps({'type': 'delta', 'content': delta}, ensure_ascii=False)}\n\n"

                answer = "".join(answer_parts)
                public_citations = [
                    {
                        "document_id": item["document_id"],
                        "document_name": item["document_name"],
                        "page": item["page"],
                        "section": item["section"],
                        "snippet": item["snippet"],
                        "score": item["score"],
                    }
                    for item in citations
                ]
                yield f"data: {json.dumps({'type': 'done', 'session_id': str(session.id), 'citations': public_citations, 'language': lang}, ensure_ascii=False)}\n\n"
                db.add(Message(session_id=session.id, role="user", content=payload.message))
                db.add(
                    Message(
                        session_id=session.id,
                        role="assistant",
                        content=answer,
                        citations=public_citations,
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

    answer, citations, lang = await rag.answer(db, payload.message, doc_ids or None, history)
    db.add(Message(session_id=session.id, role="user", content=payload.message))
    db.add(
        Message(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations=citations,
        )
    )
    await db.commit()

    return ChatResponse(
        session_id=session.id,
        answer=answer,
        citations=citations,
        language=lang,
    )
