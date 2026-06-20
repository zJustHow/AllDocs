import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings
from app.services.agent.service import AgentRAGService
from app.services.agent.state import AgentStep


def _make_service() -> AgentRAGService:
    settings = Settings(
        inference_url="http://inference",
        rerank_enabled=False,
        hybrid_enabled=False,
        rag_agent_max_steps=3,
        rag_agent_max_retrievals=5,
    )
    with (
        patch("app.services.embedding_provider.get_embedding_service", return_value=MagicMock()),
        patch("app.services.rag.VectorStore", return_value=MagicMock()),
        patch("app.services.rag.get_embedding_service", return_value=MagicMock()),
    ):
        return AgentRAGService(settings)


def test_agent_run_finish_after_search() -> None:
    service = _make_service()
    chunk_id = str(uuid.uuid4())
    service.rag.search_chunks = AsyncMock(
        return_value=[
            {
                "chunk_id": chunk_id,
                "document_id": "doc-1",
                "document_name": "Manual",
                "page": 3,
                "section": "Alarm",
                "snippet": "E001",
                "text": "E001 伺服异常",
                "score": 0.9,
                "assets": [],
            }
        ]
    )

    call_count = 0

    async def fake_decide_stream(_question: str, steps: list, **_kwargs) -> AsyncMock:
        nonlocal call_count
        call_count += 1
        if not steps:
            payload = {
                "thought": "检索",
                "reasoning_content": "",
                "action": "search_chunks",
                "action_input": {"query": "E001"},
            }
        else:
            payload = {
                "thought": "完成",
                "reasoning_content": "",
                "action": "finish",
                "action_input": {"reason": "ok"},
            }
        yield {"type": "result", "payload": payload}

    service.llm.decide_agent_action_stream = fake_decide_stream

    result = asyncio.run(
        service.run(AsyncMock(), "E001 是什么报警", doc_ids=None, filters=None)
    )

    assert call_count >= 1
    assert result.clarification is None
    assert result.fallback_message is None
    assert len(result.steps) == 2
    assert result.steps[0].action == "search_chunks"
    assert len(result.evidence) == 1
    assert result.evidence[0]["from_semantic_search"] is True


def test_agent_run_ask_user_returns_clarification() -> None:
    service = _make_service()

    async def fake_decide_stream(_question: str, _steps: list, **_kwargs) -> AsyncMock:
        yield {
            "type": "result",
            "payload": {
                "thought": "需要型号",
                "reasoning_content": "",
                "action": "ask_user",
                "action_input": {"question": "请提供设备型号。"},
            },
        }

    service.llm.decide_agent_action_stream = fake_decide_stream

    result = asyncio.run(service.run(AsyncMock(), "报警怎么办", doc_ids=None, filters=None))

    assert result.clarification == "请提供设备型号。"
    assert result.evidence == []


def test_agent_run_low_relevance_fallback() -> None:
    service = _make_service()
    service.settings = service.settings.model_copy(update={"rag_min_retrieval_score": 0.8})
    service.rag.search_chunks = AsyncMock(
        return_value=[
            {
                "chunk_id": str(uuid.uuid4()),
                "document_id": "doc-1",
                "document_name": "Manual",
                "page": 1,
                "snippet": "无关",
                "text": "无关内容",
                "score": 0.1,
                "assets": [],
            }
        ]
    )

    async def fake_decide_stream(_question: str, steps: list, **_kwargs) -> AsyncMock:
        if not steps:
            yield {
                "type": "result",
                "payload": {
                    "thought": "检索",
                    "reasoning_content": "",
                    "action": "search_chunks",
                    "action_input": {"query": "test"},
                },
            }
        else:
            yield {
                "type": "result",
                "payload": {
                    "thought": "done",
                    "reasoning_content": "",
                    "action": "finish",
                    "action_input": {"reason": "ok"},
                },
            }

    service.llm.decide_agent_action_stream = fake_decide_stream

    result = asyncio.run(service.run(AsyncMock(), "随机问题", doc_ids=None, filters=None))

    assert result.fallback_message is not None
    assert "相关性" in result.fallback_message


def test_agent_run_executes_multiple_tool_calls_in_parallel() -> None:
    service = _make_service()
    chunk_id = str(uuid.uuid4())
    search_chunk = {
        "chunk_id": chunk_id,
        "document_id": "doc-1",
        "document_name": "Manual",
        "page": 3,
        "section": "Alarm",
        "snippet": "E001",
        "text": "E001 伺服异常",
        "score": 0.9,
        "assets": [],
    }
    neighbor_chunk = {
        **search_chunk,
        "text": "E001 完整操作步骤",
    }

    service.rag.search_chunks = AsyncMock(return_value=[search_chunk])
    service.rag.read_neighbor_chunks = AsyncMock(return_value=([neighbor_chunk], None))

    async def fake_decide_stream(_question: str, steps: list, **_kwargs) -> AsyncMock:
        if not steps:
            yield {
                "type": "result",
                "payload": {
                    "thought": "并行检索与扩展",
                    "reasoning_content": "",
                    "actions": [
                        {
                            "action": "search_chunks",
                            "action_input": {"query": "E001"},
                            "tool_call_id": "call_search",
                        },
                        {
                            "action": "read_neighbor_chunks",
                            "action_input": {"chunk_id": chunk_id},
                            "tool_call_id": "call_neighbor",
                        },
                    ],
                    "action": "search_chunks",
                    "action_input": {"query": "E001"},
                },
            }
        else:
            yield {
                "type": "result",
                "payload": {
                    "thought": "完成",
                    "reasoning_content": "",
                    "action": "finish",
                    "action_input": {"reason": "ok"},
                },
            }

    service.llm.decide_agent_action_stream = fake_decide_stream

    result = asyncio.run(
        service.run(AsyncMock(), "E001 怎么处理", doc_ids=None, filters=None)
    )

    assert len(result.steps) == 2
    assert result.steps[0].action == "search_chunks + read_neighbor_chunks"
    assert len(result.steps[0].tool_calls) == 2
    assert result.steps[0].tool_calls[0].action == "search_chunks"
    assert result.steps[0].tool_calls[1].action == "read_neighbor_chunks"
    assert len(result.evidence) == 1
    service.rag.search_chunks.assert_awaited_once()
    service.rag.read_neighbor_chunks.assert_awaited_once()
