import uuid

from app.services.agent.observation_compress import (
    build_evidence_index,
    compress_observation,
)
from app.services.agent.state import AgentStep
from app.services.agent.tool_definitions import build_agent_messages


def _search_observation(chunk_id: str, snippet: str) -> str:
    return (
        "检索工具：search_chunks，命中 1 条：\n\n"
        f"[1] Manual.pdf p.3 §Alarm id={chunk_id}\n"
        f"{snippet}"
    )


def test_compress_observation_keeps_recent_step() -> None:
    observation = _search_observation("abc", "x" * 300)
    assert compress_observation(
        observation,
        action="search_chunks",
        is_recent=True,
    ) == observation


def test_compress_observation_shortens_historical_search() -> None:
    chunk_id = str(uuid.uuid4())
    long_snippet = "E001 伺服异常 " + "x" * 300
    observation = _search_observation(chunk_id, long_snippet)

    compressed = compress_observation(
        observation,
        action="search_chunks",
        is_recent=False,
        history_snippet_max=60,
    )

    assert "历史步压缩" in compressed
    assert f"id={chunk_id}" in compressed
    assert long_snippet not in compressed
    assert "E001 伺服异常" in compressed


def test_compress_observation_strips_read_neighbor_snippet() -> None:
    chunk_id = str(uuid.uuid4())
    observation = (
        "检索工具：read_neighbor_chunks，命中 1 条：\n\n"
        f"[1] Manual.pdf p.5 §Setup id={chunk_id}\n"
        + ("完整正文 " * 50)
    )

    compressed = compress_observation(
        observation,
        action="read_neighbor_chunks",
        is_recent=False,
    )

    assert "正文见证据池" in compressed
    assert f"id={chunk_id}" in compressed
    assert "完整正文" not in compressed


def test_compress_observation_outline_preview() -> None:
    outline = "\n".join(f"第{i}章 标题{i}" for i in range(1, 12))

    compressed = compress_observation(
        outline,
        action="list_outline",
        is_recent=False,
        outline_preview_lines=5,
    )

    assert "共 11 行" in compressed
    assert "第1章" in compressed
    assert "第11章" not in compressed
    assert "lookup_toc" in compressed


def test_compress_observation_batch() -> None:
    chunk_id = str(uuid.uuid4())
    observation = (
        "并行检索 2 路，合计命中 2 条：\n"
        "\n--- 检索 1：原因 · 命中 1 条 ---\n"
        f"  [1] Manual.pdf p.1 id={chunk_id}\n"
        "    " + ("原因说明 " * 40)
        + "\n--- 检索 2：排查 · 命中 0 条 ---\n"
        "（无结果）"
    )

    compressed = compress_observation(
        observation,
        action="search_chunks_batch",
        is_recent=False,
        history_snippet_max=40,
    )

    assert "历史步压缩" in compressed
    assert f"id={chunk_id}" in compressed
    assert "原因说明" in compressed
    assert ("原因说明 " * 40).strip() not in compressed


def test_build_evidence_index_lists_chunk_ids() -> None:
    chunk_id = str(uuid.uuid4())
    index = build_evidence_index(
        [
            {
                "document_name": "Manual.pdf",
                "page": 3,
                "section": "Alarm",
                "chunk_id": chunk_id,
                "chunk_index": 7,
                "score": 0.77,
                "assets": [
                    {"type": "table", "figure_number": "2-1"},
                ],
            }
        ]
    )

    assert "证据池 1 条" in index
    assert f"id={chunk_id}" in index
    assert "assets=table" in index
    assert "fig=2-1" in index
    assert "score=0.770" in index
    assert "idx=7" in index


def test_build_agent_messages_compresses_only_historical_steps() -> None:
    chunk_id = str(uuid.uuid4())
    long_snippet = "报警详情 " + "y" * 300
    steps = [
        AgentStep(
            step=1,
            thought="第一轮检索",
            action="search_chunks",
            action_input={"query": "E001"},
            observation=_search_observation(chunk_id, long_snippet),
            reasoning_content="历史推理",
        ),
        AgentStep(
            step=2,
            thought="第二轮检索",
            action="search_chunks",
            action_input={"query": "排查"},
            observation=_search_observation(chunk_id, "第二轮完整片段"),
            reasoning_content="最新推理",
        ),
    ]

    messages = build_agent_messages(
        "E001 报警",
        steps,
        evidence=[{"document_name": "Manual.pdf", "chunk_id": chunk_id}],
        keep_full_observation_steps=1,
        history_snippet_max=60,
    )

    first_tool = messages[2]["content"]
    second_tool = messages[4]["content"]

    assert "历史步压缩" in first_tool
    assert long_snippet not in first_tool
    assert "reasoning_content" not in messages[1]
    assert second_tool == steps[1].observation
    assert messages[3].get("reasoning_content") == "最新推理"
    assert messages[-1]["role"] == "user"
    assert "证据池" in messages[-1]["content"]


def test_build_agent_messages_single_step_stays_full() -> None:
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

    assert messages[2]["content"] == "命中 1 条"
    assert len(messages) == 3
