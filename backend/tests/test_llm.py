import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.config import Settings
from app.services.llm import (
    LLMService,
    _build_agent_system_prompt,
    _build_system_prompt,
    _question_line,
    _user_context_block,
)


async def _collect(iterator):
    return [item async for item in iterator]


def test_build_system_prompt_includes_lang_rules() -> None:
    zh_prompt = _build_system_prompt("zh")
    en_prompt = _build_system_prompt("en")

    assert "Markdown" in zh_prompt
    assert "3.xxx" in zh_prompt
    assert "全文中文" in zh_prompt
    assert "Respond entirely in English" in en_prompt
    assert "new line" in en_prompt


def test_build_agent_system_prompt_includes_lang_rules() -> None:
    zh_prompt = _build_agent_system_prompt("zh")
    en_prompt = _build_agent_system_prompt("en")

    assert "检索 Agent" in zh_prompt
    assert "与用户问题相同语言" in zh_prompt
    assert "retrieval Agent" in en_prompt
    assert "user's question" in en_prompt


def test_question_line_adds_history_note_when_needed() -> None:
    line = _question_line("en", "What is E001?", [{"role": "user", "content": "prior"}])
    assert line.startswith("Question：")
    assert "Prior turns" in line


def test_user_context_block_wraps_context() -> None:
    block = _user_context_block("chunk body", "问题：测试")
    assert "<context>" in block
    assert "chunk body" in block
    assert "问题：测试" in block


def test_build_messages_limits_history_and_appends_user_block() -> None:
    service = LLMService(Settings(llm_api_key="k", llm_api_base_url="http://x"))
    history = [{"role": "user", "content": f"turn-{index}"} for index in range(8)]

    messages = service.build_messages(
        "当前问题",
        "证据正文",
        history,
        lang="zh",
    )

    assert messages[0]["role"] == "system"
    assert len([message for message in messages if message["role"] == "user"]) == 7
    assert "证据正文" in messages[-1]["content"]
    assert messages[1]["content"] == "turn-2"
    assert len(messages) == 8


def test_build_streamed_agent_message_merges_tool_arguments() -> None:
    tool_calls_acc = {
        0: {
            "id": "call_1",
            "name": "search_chunks",
            "arguments_parts": ['{"query":', '"E001"}'],
        }
    }
    message = LLMService._build_streamed_agent_message(
        "检索",
        "推理",
        tool_calls_acc,
    )

    assert message.content == "检索"
    assert message.reasoning_content == "推理"
    assert message.tool_calls[0].function.name == "search_chunks"
    assert message.tool_calls[0].function.arguments == '{"query":"E001"}'


def test_chat_stream_yields_text_deltas() -> None:
    service = LLMService(Settings(llm_api_key="k", llm_api_base_url="http://x"))

    class _Delta:
        def __init__(self, content: str | None) -> None:
            self.content = content

    class _Choice:
        def __init__(self, content: str | None) -> None:
            self.delta = _Delta(content)

    class _Chunk:
        def __init__(self, content: str | None) -> None:
            self.choices = [_Choice(content)]

    async def fake_stream():
        yield _Chunk("Hello ")
        yield _Chunk("world")

    service.client.chat.completions.create = AsyncMock(return_value=fake_stream())

    deltas = asyncio.run(_collect(service.chat_stream("问题", "ctx", lang="zh")))

    assert deltas == ["Hello ", "world"]


def test_decide_agent_action_stream_emits_result_payload() -> None:
    service = LLMService(
        Settings(
            llm_api_key="k",
            llm_api_base_url="http://x",
            llm_model="test-model",
            rag_agent_history_snippet_max=60,
            rag_agent_keep_full_observation_steps=1,
            rag_agent_outline_preview_lines=5,
        )
    )

    class _Function:
        name = "search_chunks"
        arguments = '{"query":"报警"}'

    class _ToolCall:
        index = 0
        id = "call_1"
        function = _Function()

    class _Delta:
        content = "先检索"
        reasoning_content = ""
        tool_calls = [_ToolCall()]

    class _Choice:
        delta = _Delta()

    class _Chunk:
        choices = [_Choice()]

    async def fake_stream():
        yield _Chunk()

    service.client.chat.completions.create = AsyncMock(return_value=fake_stream())

    events = asyncio.run(_collect(service.decide_agent_action_stream("报警代码", [])))

    assert events[0]["type"] == "delta"
    assert events[-1]["type"] == "result"
    assert events[-1]["payload"]["action"] == "search_chunks"
    assert events[-1]["payload"]["action_input"]["query"] == "报警"
