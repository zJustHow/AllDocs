from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Session, User
from app.services.auth_service import resolve_chat_doc_ids

CHAT_HISTORY_MAX_TURNS = 6
CHAT_HISTORY_MAX_MESSAGES = CHAT_HISTORY_MAX_TURNS * 2


async def load_recent_chat_history(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    max_messages: int = CHAT_HISTORY_MAX_MESSAGES,
) -> list[dict[str, str]]:
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    messages = list(result.scalars().all())
    messages.reverse()
    return [{"role": message.role, "content": message.content} for message in messages]


async def get_or_create_chat_session(
    db: AsyncSession,
    *,
    user: User,
    session_id: uuid.UUID | None,
    requested_doc_ids: list[uuid.UUID],
) -> tuple[Session, list[uuid.UUID]]:
    effective_doc_ids = await resolve_chat_doc_ids(db, user, requested_doc_ids)
    doc_id_strings = [str(doc_id) for doc_id in effective_doc_ids]

    if session_id:
        session = await db.get(Session, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.user_id and session.user_id != user.id:
            raise HTTPException(status_code=403, detail="Session access denied")
        if not session.user_id:
            session.user_id = user.id
        return session, effective_doc_ids

    session = Session(user_id=user.id, doc_ids=doc_id_strings)
    db.add(session)
    await db.flush()
    return session, effective_doc_ids
