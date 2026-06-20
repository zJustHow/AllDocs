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
    SEARCH_SNIPPET_MAX,
    _format_batch_observation,
    _format_chunk_header,
    _format_chunks,
    _merge_batch_chunks,
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
    assert count_retrieval_units("list_outline", {}, max_batch=2) == 0
    assert count_retrieval_units("lookup_toc", {}, max_batch=2) == 0
    assert count_retrieval_units("read_neighbor_chunks", {"chunk_id": "x"}, max_batch=2) == 0


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
    merge_chunks_into_evidence(evidence, seen, [chunk], source_action="read_neighbor_chunks")
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
    assert payload["actions"][0]["action"] == "search_chunks"


def test_parse_agent_tool_response_maps_unknown_tool_to_finish() -> None:
    call = SimpleNamespace(
        function=SimpleNamespace(name="not_a_real_tool", arguments="{}"),
    )
    message = SimpleNamespace(content="", reasoning_content="", tool_calls=[call])

    payload = parse_agent_tool_response(message)

    assert payload["action"] == "finish"
    assert payload["action_input"]["reason"] == "no valid tool calls"


def test_parse_agent_tool_response_returns_all_tool_calls() -> None:
    calls = [
        SimpleNamespace(
            id="call_a",
            function=SimpleNamespace(
                name="search_chunks",
                arguments='{"query":"E001"}',
            ),
        ),
        SimpleNamespace(
            id="call_b",
            function=SimpleNamespace(
                name="read_neighbor_chunks",
                arguments='{"chunk_id":"11111111-1111-1111-1111-111111111111"}',
            ),
        ),
    ]
    message = SimpleNamespace(content="并行检索与扩展", reasoning_content="", tool_calls=calls)

    payload = parse_agent_tool_response(message)

    assert len(payload["actions"]) == 2
    assert payload["actions"][0]["action"] == "search_chunks"
    assert payload["actions"][1]["action"] == "read_neighbor_chunks"
    assert payload["actions"][1]["tool_call_id"] == "call_b"


def test_build_agent_messages_includes_multiple_tool_results() -> None:
    from app.services.agent.state import AgentStep, AgentToolCall

    chunk_id = str(uuid.uuid4())
    steps = [
        AgentStep(
            step=1,
            thought="并行",
            action="search_chunks + read_neighbor_chunks",
            action_input={"calls": []},
            observation="merged",
            tool_calls=[
                AgentToolCall(
                    action="search_chunks",
                    action_input={"query": "E001"},
                    observation="命中 1 条",
                    tool_call_id="call_a",
                ),
                AgentToolCall(
                    action="read_neighbor_chunks",
                    action_input={"chunk_id": chunk_id},
                    observation="相邻 2 条",
                    tool_call_id="call_b",
                ),
            ],
        )
    ]
    messages = build_agent_messages("报警代码 E001", steps)

    assert len(messages[1]["tool_calls"]) == 2
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_a"
    assert messages[3]["role"] == "tool"
    assert messages[3]["tool_call_id"] == "call_b"


def test_agent_tool_names_match_definitions() -> None:
    assert "search_chunks" in AGENT_TOOL_NAMES
    assert "read_neighbor_chunks" in AGENT_TOOL_NAMES
    assert "list_documents" in AGENT_TOOL_NAMES
    assert "lookup_asset" in AGENT_TOOL_NAMES
    assert "read_pages" in AGENT_TOOL_NAMES
    assert "read_chunks" not in AGENT_TOOL_NAMES


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
    rag.read_neighbor_chunks = AsyncMock(return_value=([], None))
    return AgentToolRegistry(rag)


def test_format_chunks_read_mode_returns_full_text() -> None:
    long_body = "步骤一：打开电源。" + ("详细说明 " * 80)
    chunk_id = str(uuid.uuid4())
    observation = _format_chunks(
        [
            {
                "chunk_id": chunk_id,
                "document_name": "Manual.pdf",
                "page": 12,
                "section": "Setup",
                "chunk_index": 4,
                "text": long_body,
                "snippet": long_body[:300],
                "assets": [],
            }
        ],
        source_tool="read_neighbor_chunks",
        full_text=True,
    )

    assert long_body in observation
    assert len(observation) > 300
    assert f"id={chunk_id}" in observation
    assert "idx=4" in observation


def test_format_chunk_header_includes_figure_number_and_score() -> None:
    header = _format_chunk_header(
        {
            "document_name": "Manual.pdf",
            "page": 3,
            "section": "Alarm",
            "score": 0.8123,
            "chunk_id": "abc",
            "assets": [
                {"type": "figure", "figure_number": "4-7"},
                {"type": "table", "figure_number": "2-1"},
            ],
        },
        index=1,
    )

    assert "fig=4-7,2-1" in header
    assert "score=0.812" in header
    assert "assets=figure,table" in header


def test_merge_batch_chunks_dedupes_and_keeps_highest_score() -> None:
    shared_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    merged = _merge_batch_chunks(
        [
            (
                "原因",
                [
                    {
                        "chunk_id": shared_id,
                        "document_name": "Manual.pdf",
                        "score": 0.4,
                        "text": "low",
                    },
                    {
                        "chunk_id": other_id,
                        "document_name": "Manual.pdf",
                        "score": 0.7,
                        "text": "other",
                    },
                ],
            ),
            (
                "排查",
                [
                    {
                        "chunk_id": shared_id,
                        "document_name": "Manual.pdf",
                        "score": 0.9,
                        "text": "high",
                    }
                ],
            ),
        ]
    )

    assert len(merged) == 2
    assert merged[0]["chunk_id"] == shared_id
    assert merged[0]["score"] == 0.9
    assert merged[1]["chunk_id"] == other_id


def test_format_batch_observation_marks_duplicate_hits() -> None:
    shared_id = str(uuid.uuid4())
    observation = _format_batch_observation(
        [
            (
                "原因",
                [
                    {
                        "chunk_id": shared_id,
                        "document_name": "Manual.pdf",
                        "page": 3,
                        "snippet": "首次出现",
                        "text": "首次出现",
                        "assets": [],
                    }
                ],
            ),
            (
                "排查",
                [
                    {
                        "chunk_id": shared_id,
                        "document_name": "Manual.pdf",
                        "page": 3,
                        "snippet": "重复出现",
                        "text": "重复出现",
                        "assets": [],
                    },
                    {
                        "chunk_id": str(uuid.uuid4()),
                        "document_name": "Manual.pdf",
                        "page": 4,
                        "snippet": "另一条",
                        "text": "另一条",
                        "assets": [],
                    },
                ],
            ),
        ]
    )

    assert "去重后 2 条" in observation
    assert "dup@检索1" in observation
    assert "首次出现" in observation
    assert "重复出现" not in observation
    assert "另一条" in observation


def test_execute_list_documents(tool_registry: AgentToolRegistry) -> None:
    doc_id = uuid.uuid4()
    document = MagicMock()
    document.id = doc_id
    document.name = "Manual.pdf"
    document.page_count = 120
    document.status.value = "ready"

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [document])))
    )

    observation, chunks, units = asyncio.run(
        tool_registry.execute(
            db,
            "list_documents",
            {},
            question="q",
            doc_ids=[doc_id],
            explicit_filters=None,
        )
    )

    assert units == 0
    assert chunks == []
    assert "Manual.pdf" in observation
    assert str(doc_id) in observation
    assert "pages=120" in observation


def test_execute_lookup_asset(tool_registry: AgentToolRegistry) -> None:
    chunk_id = str(uuid.uuid4())
    tool_registry.rag._load_chunks = AsyncMock(
        return_value=[
            {
                "chunk_id": chunk_id,
                "document_name": "Manual.pdf",
                "page": 10,
                "snippet": "参数表",
                "text": "额定电压 220V",
                "assets": [{"type": "table", "figure_number": "2-1"}],
            }
        ]
    )

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(all=lambda: [(chunk_id,)])
    )

    observation, chunks, units = asyncio.run(
        tool_registry.execute(
            db,
            "lookup_asset",
            {"figure_number": "表2-1", "kind": "table"},
            question="q",
            doc_ids=None,
            explicit_filters=None,
        )
    )

    assert units == 0
    assert len(chunks) == 1
    assert "lookup_asset" in observation
    assert "fig=2-1" in observation
    tool_registry.rag._load_chunks.assert_awaited_once()


def test_execute_read_pages(tool_registry: AgentToolRegistry) -> None:
    chunk_id = str(uuid.uuid4())
    tool_registry.rag.read_pages = AsyncMock(
        return_value=(
            [
                {
                    "chunk_id": chunk_id,
                    "document_name": "Manual.pdf",
                    "page": 45,
                    "text": "第45页完整正文",
                    "snippet": "第45页",
                    "assets": [],
                }
            ],
            None,
        )
    )

    observation, chunks, units = asyncio.run(
        tool_registry.execute(
            AsyncMock(),
            "read_pages",
            {"page": 45},
            question="q",
            doc_ids=None,
            explicit_filters=None,
        )
    )

    assert units == 0
    assert len(chunks) == 1
    assert "第45页完整正文" in observation
    assert "p.45" in observation


def test_format_chunks_search_mode_truncates_snippet() -> None:
    long_body = "报警说明 " + "x" * 400
    observation = _format_chunks(
        [
            {
                "document_name": "Manual.pdf",
                "page": 1,
                "snippet": long_body,
                "text": long_body,
                "score": 0.55,
                "assets": [],
            }
        ],
        source_tool="search_chunks",
    )

    assert "score=0.550" in observation
    assert len(long_body) > SEARCH_SNIPPET_MAX
    assert long_body not in observation
    assert long_body[:SEARCH_SNIPPET_MAX] in observation


def test_execute_read_neighbor_chunks_returns_full_text(
    tool_registry: AgentToolRegistry,
) -> None:
    chunk_id = uuid.uuid4()
    long_body = "完整操作步骤 " + ("延续内容 " * 60)
    tool_registry.rag.read_neighbor_chunks = AsyncMock(
        return_value=(
            [
                {
                    "chunk_id": str(chunk_id),
                    "document_name": "Manual.pdf",
                    "page": 8,
                    "section": "Operation",
                    "chunk_index": 2,
                    "text": long_body,
                    "snippet": long_body[:300],
                    "assets": [{"type": "table", "figure_number": "3-1"}],
                }
            ],
            None,
        )
    )

    observation, chunks, units = asyncio.run(
        tool_registry.execute(
            AsyncMock(),
            "read_neighbor_chunks",
            {"chunk_id": str(chunk_id)},
            question="q",
            doc_ids=None,
            explicit_filters=None,
        )
    )

    assert units == 0
    assert len(chunks) == 1
    assert long_body in observation
    assert "fig=3-1" in observation
    assert "idx=2" in observation


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
