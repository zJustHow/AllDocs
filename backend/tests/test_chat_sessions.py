from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Message, Session
from app.services.chat_sessions import CHAT_HISTORY_MAX_MESSAGES, load_recent_chat_history
from tests.sqlite_schema import create_sqlite_schema


@pytest.fixture
async def auth_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda bind: create_sqlite_schema(bind, Base.metadata))

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_load_recent_chat_history_limits_to_latest_messages(
    auth_db: AsyncSession,
) -> None:
    session = Session(doc_ids=[])
    auth_db.add(session)
    await auth_db.flush()

    base_time = datetime.now(UTC)
    for index in range(20):
        auth_db.add(
            Message(
                session_id=session.id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"message-{index}",
                created_at=base_time + timedelta(seconds=index),
            )
        )
    await auth_db.commit()

    history = await load_recent_chat_history(auth_db, session.id)
    assert len(history) == CHAT_HISTORY_MAX_MESSAGES
    assert history[0]["content"] == f"message-{20 - CHAT_HISTORY_MAX_MESSAGES}"
    assert history[-1]["content"] == "message-19"
    assert history[-1]["role"] == "assistant"
