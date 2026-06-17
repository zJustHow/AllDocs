"""Shared agent run + synthesis pipeline for chat SSE and voice WebSocket."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Message
from app.services.agent.service import AgentRAGService
from app.services.agent.state import AgentResult, OnAgentStep
from app.services.chunk_filter import ChunkFilter
from app.services.citations_util import finalize_answer, public_citations
from app.services.vision_util import collect_vision_asset_ids, prepare_vision_images


async def persist_turn(
    db: AsyncSession,
    session_id: UUID,
    user_message: str,
    assistant_content: str,
    citations: list[dict],
    embeds: list[dict] | None = None,
) -> None:
    db.add(Message(session_id=session_id, role="user", content=user_message))
    db.add(
        Message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            citations=citations,
            embeds=embeds or [],
        )
    )
    await db.commit()


async def _stream_synthesis(
    agent: AgentRAGService,
    db: AsyncSession,
    message: str,
    result: AgentResult,
    history: list[dict[str, str]],
    settings: Settings,
    lang: str,
) -> AsyncIterator[dict]:
    if result.fallback_message:
        yield {
            "type": "fallback",
            "content": result.fallback_message,
            "language": lang,
        }
        return

    refs = public_citations(result.evidence)
    yield {"type": "citations", "citations": refs}

    vision_images = await prepare_vision_images(db, result.evidence, settings)
    allowed_embed_asset_ids = collect_vision_asset_ids(result.evidence, vision_images)
    answer_parts: list[str] = []
    async for delta in agent.iter_synthesis(
        message, result.evidence, history, vision_images, lang=lang
    ):
        answer_parts.append(delta)
        yield {"type": "delta", "content": delta}

    answer, refs, embeds = finalize_answer(
        "".join(answer_parts),
        result.evidence,
        allowed_embed_asset_ids=allowed_embed_asset_ids,
    )
    if embeds:
        yield {"type": "embeds", "embeds": embeds}
    yield {
        "type": "complete",
        "answer": answer,
        "citations": refs,
        "embeds": embeds,
        "language": lang,
    }


async def stream_agent_answer(
    agent: AgentRAGService,
    db: AsyncSession,
    message: str,
    doc_ids: list[UUID] | None,
    chunk_filters: ChunkFilter | None,
    history: list[dict[str, str]],
    settings: Settings,
    lang: str,
    *,
    on_agent_step: OnAgentStep | None = None,
) -> AsyncIterator[dict]:
    """Yield agent step events, then synthesis events (citations/delta/embeds/complete)."""
    yield {"type": "status", "stage": "agent"}

    step_queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def queue_step(event: dict) -> None:
        await step_queue.put(event)
        if on_agent_step is not None:
            await on_agent_step(event)

    async def run_agent() -> AgentResult:
        try:
            return await agent.run(
                db,
                message,
                doc_ids,
                chunk_filters,
                history,
                on_step=queue_step,
                skip_synthesis=True,
            )
        finally:
            await step_queue.put(None)

    agent_task = asyncio.create_task(run_agent())
    while True:
        event = await step_queue.get()
        if event is None:
            break
        if on_agent_step is None:
            yield event

    result = await agent_task
    async for event in _stream_synthesis(agent, db, message, result, history, settings, lang):
        yield event
