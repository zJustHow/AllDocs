import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.services.agent.tool_definitions import (
    AGENT_TOOL_NAMES,
    build_agent_messages,
    parse_agent_tool_response,
)
from app.services.agent.tools import (
    AgentToolRegistry,
    count_retrieval_units,
    merge_chunks_into_evidence,
    parse_batch_searches,
    parse_tool_filters,
)


def test_parse_batch_searches_skips_empty_queries() -> None:
    searches = parse_batch_searches(
        {
            "searches": [
                {"query": "零点标定"},
                {"query": ""},
                {"query": "伺服报警"},
            ]
        },
        "fallback",
        max_items=5,
    )

    assert len(searches) == 2
    assert searches[0]["query"] == "零点标定"


def test_count_retrieval_units_for_batch_and_single() -> None:
    batch_input = {
        "searches": [{"query": "a"}, {"query": "b"}, {"query": "c"}],
    }
    assert count_retrieval_units("search_chunks_batch", batch_input, max_batch=2) == 2
    assert count_retrieval_units("search_chunks", {"query": "x"}, max_batch=2) == 1
    assert count_retrieval_units("finish", {}, max_batch=2) == 0


def test_parse_tool_filters_rejects_invalid_payload() -> None:
    doc_id = uuid.uuid4()
    filters = parse_tool_filters({"page_gte": "bad"}, [doc_id])

    assert filters.document_ids == [doc_id]
    assert filters.page_gte is None


def test_merge_chunks_into_evidence_marks_semantic_search() -> None:
    evidence: list[dict] = []
    seen: set[str] = set()
    chunk = {
        "chunk_id": "c1",
        "document_id": "d1",
        "page": 1,
        "section": "Intro",
        "text": "body",
    }

    merge_chunks_into_evidence(evidence, seen, [chunk], source_action="search_chunks")

    assert len(evidence) == 1
    assert evidence[0]["from_semantic_search"] is True
    merge_chunks_into_evidence(evidence, seen, [chunk], source_action="read_chunks")
    assert len(evidence) == 1


def test_build_agent_messages_includes_tool_results() -> None:
    from app.services.agent.state import AgentStep

    steps = [
        AgentStep(
            step=1,
            thought="检索报警",
            action="search_chunks",
            action_input={"query": "E001"},
            observation="命中 1 条",
            reasoning_content="",
        )
    ]
    messages = build_agent_messages("报警代码 E001", steps)

    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["function"]["name"] == "search_chunks"
    assert messages[2]["role"] == "tool"
    assert messages[2]["content"] == "命中 1 条"


def test_parse_agent_tool_response_normalizes_tool_call() -> None:
    call = SimpleNamespace(
        function=SimpleNamespace(
            name="search_chunks",
            arguments='{"query":"零点标定"}',
        )
    )
    message = SimpleNamespace(
        content="先检索",
        reasoning_content="",
        tool_calls=[call],
    )

    payload = parse_agent_tool_response(message)

    assert payload["action"] == "search_chunks"
    assert payload["action_input"]["query"] == "零点标定"
    assert payload["thought"] == "先检索"


def test_parse_agent_tool_response_maps_unknown_tool_to_finish() -> None:
    call = SimpleNamespace(
        function=SimpleNamespace(name="not_a_real_tool", arguments="{}"),
    )
    message = SimpleNamespace(content="", reasoning_content="", tool_calls=[call])

    payload = parse_agent_tool_response(message)

    assert payload["action"] == "finish"
    assert "unknown tool" in payload["action_input"]["reason"]


def test_agent_tool_names_match_definitions() -> None:
    assert "search_chunks" in AGENT_TOOL_NAMES
    assert "read_neighbor_chunks" in AGENT_TOOL_NAMES


@pytest.fixture
def tool_registry() -> AgentToolRegistry:
    rag = MagicMock()
    rag.settings = Settings(rag_top_k=5, rag_batch_search_max=3)
    rag.search_chunks = AsyncMock(
        return_value=[
            {
                "chunk_id": str(uuid.uuid4()),
                "document_name": "Manual.pdf",
                "page": 2,
                "section": "Alarm",
                "snippet": "E001 伺服异常",
                "text": "E001 伺服异常",
                "assets": [],
            }
        ]
    )
    rag._embed_queries = AsyncMock(return_value=[[0.1, 0.2]])
    rag.read_chunks = AsyncMock(return_value=[])
    rag.read_neighbor_chunks = AsyncMock(return_value=([], None))
    return AgentToolRegistry(rag)


def test_execute_search_chunks_formats_observation(tool_registry: AgentToolRegistry) -> None:
    db = AsyncMock()

    observation, chunks, units = asyncio.run(
        tool_registry.execute(
            db,
            "search_chunks",
            {"query": "伺服报警"},
            question="伺服报警怎么办",
            doc_ids=None,
            explicit_filters=None,
        )
    )

    assert units == 1
    assert len(chunks) == 1
    assert "search_chunks" in observation
    assert "Manual.pdf" in observation


def test_execute_finish_returns_reason(tool_registry: AgentToolRegistry) -> None:
    observation, chunks, units = asyncio.run(
        tool_registry.execute(
            AsyncMock(),
            "finish",
            {"reason": "证据充分"},
            question="q",
            doc_ids=None,
            explicit_filters=None,
        )
    )

    assert units == 0
    assert chunks == []
    assert "证据充分" in observation


def test_execute_read_chunks_rejects_invalid_ids(tool_registry: AgentToolRegistry) -> None:
    observation, chunks, units = asyncio.run(
        tool_registry.execute(
            AsyncMock(),
            "read_chunks",
            {"chunk_ids": ["not-a-uuid"]},
            question="q",
            doc_ids=None,
            explicit_filters=None,
        )
    )

    assert units == 1
    assert chunks == []
    assert "UUID" in observation
