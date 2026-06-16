from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.services.agent import AgentRAGService
from app.services.agent.state import AgentResult, OnAgentStep
from app.services.chunk_filter import ChunkFilter


async def run_agent_answer(
    db: AsyncSession,
    question: str,
    doc_ids: list[UUID] | None,
    filters: ChunkFilter | None,
    chat_history: list[dict[str, str]] | None,
    *,
    agent: AgentRAGService | None = None,
    on_step: OnAgentStep | None = None,
    settings: Settings | None = None,
    skip_synthesis: bool = False,
) -> AgentResult:
    service = agent or AgentRAGService(settings)
    return await service.run(
        db,
        question,
        doc_ids,
        filters,
        chat_history,
        on_step=on_step,
        skip_synthesis=skip_synthesis,
    )
