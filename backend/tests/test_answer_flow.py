import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.config import Settings
from app.services.agent.answer_flow import _stream_synthesis, stream_agent_answer
from app.services.agent.state import AgentResult, AgentStep


async def _collect_events(iterator) -> list[dict]:
    return [event async for event in iterator]


def test_stream_synthesis_emits_clarification() -> None:
    agent = MagicMock()
    result = AgentResult(
        answer="",
        citations=[],
        language="zh",
        steps=[],
        evidence=[],
        clarification="请补充设备型号。",
    )

    events = asyncio.run(
        _collect_events(
            _stream_synthesis(
                agent,
                "问题",
                result,
                [],
                Settings(),
                "zh",
            )
        )
    )

    assert events == [{"type": "clarify", "content": "请补充设备型号。", "language": "zh"}]


def test_stream_synthesis_emits_fallback_without_llm() -> None:
    agent = MagicMock()
    result = AgentResult(
        answer="",
        citations=[],
        language="en",
        steps=[],
        evidence=[],
        fallback_message="Not found in the operation guide.",
    )

    events = asyncio.run(
        _collect_events(
            _stream_synthesis(
                agent,
                "question",
                result,
                [],
                Settings(),
                "en",
            )
        )
    )

    assert events[0]["type"] == "fallback"
    assert events[0]["content"] == "Not found in the operation guide."


def test_stream_synthesis_streams_answer_and_complete_payload() -> None:
    agent = MagicMock()

    async def _fake_iter_synthesis(*_args, **_kwargs):
        yield "Answer "
        yield "body."

    agent.iter_synthesis = _fake_iter_synthesis
    evidence = [
        {
            "document_id": "doc-1",
            "document_name": "Manual",
            "page": 1,
            "section": "Intro",
            "snippet": "snippet",
            "score": 0.9,
            "layout_regions": [],
        }
    ]
    result = AgentResult(
        answer="",
        citations=[],
        language="zh",
        steps=[],
        evidence=evidence,
    )

    with patch(
        "app.services.agent.answer_flow.finalize_answer_async",
        AsyncMock(
            return_value=(
                "Answer body.[1]",
                [{"ref": 1, "document_id": "doc-1"}],
                [],
            )
        ),
    ):
        events = asyncio.run(
            _collect_events(
                _stream_synthesis(
                    agent,
                    "问题",
                    result,
                    [],
                    Settings(),
                    "zh",
                )
            )
        )

    types = [event["type"] for event in events]
    assert types == ["citations", "delta", "delta", "complete"]
    assert events[-1]["answer"] == "Answer body.[1]"
    assert events[-1]["citations"] == [{"ref": 1, "document_id": "doc-1"}]


def test_stream_agent_answer_yields_steps_then_synthesis() -> None:
    agent = MagicMock()
    step = AgentStep(
        step=1,
        thought="search",
        action="semantic_search",
        action_input={"query": "alarm"},
        observation="found 1 chunk",
    )
    agent_result = AgentResult(
        answer="",
        citations=[],
        language="zh",
        steps=[step],
        evidence=[],
        fallback_message="操作指南中未找到相关信息。",
    )

    async def _fake_run(*_args, **_kwargs):
        on_step = _kwargs.get("on_step")
        if on_step is not None:
            await on_step({"type": "agent_step", "step": 1, "action": "semantic_search"})
        return agent_result

    agent.run = _fake_run

    events = asyncio.run(
        _collect_events(
            stream_agent_answer(
                agent,
                "报警代码",
                None,
                None,
                [],
                Settings(),
                "zh",
            )
        )
    )

    assert events[0] == {"type": "status", "stage": "agent"}
    assert events[1]["type"] == "agent_step"
    assert events[2]["type"] == "fallback"
