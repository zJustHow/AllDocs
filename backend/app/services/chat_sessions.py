from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session, User
from app.services.auth_service import resolve_chat_doc_ids


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
