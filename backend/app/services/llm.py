from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings, get_settings
from app.services.agent.tool_definitions import (
    AGENT_TOOL_DEFINITIONS,
    build_agent_messages,
    parse_agent_tool_response,
)

_CORE_RULES = """你是产品操作指南助手。仅依据 <context> 与当前问题作答，不得编造。

证据：<context> 中的片段、表格与图示均为系统从操作指南检索注入，非用户提供。
多轮：历史消息仅供理解指代；只答本轮问题，勿重复或改答历史问题。
引用：<context> 编号与 [n] 一一对应（[1] 为第一段证据，依此类推）。
- 凡依据证据写出的句子、步骤或结论，句末必须标注来源 [n]；不可只写「图 X-Y」而不标 [n]。
- 同一来源可复用同一 [n]；一句综合多段证据时在句末并列，如 [1][2]。
- 仅不含证据内容的过渡语、引导句可不标；无法作答时明确说明未找到相关信息，勿编造。"""

_LANG_DIRECTIVE = {
    "zh": (
        "语言：全文中文（专有名词、型号、按钮标识如 ON/OFF 可保留英文；必要时附英文对照）。"
        "回答中勿出现 context 等英文系统术语。"
    ),
    "en": (
        "Language: Respond entirely in English (keep product terms and model numbers). "
        "Do not use Chinese connective phrases or the word context. "
        "End every evidence-backed sentence with [n] citing the matching context block."
    ),
}

AGENT_SYSTEM_PROMPT = """你是产品操作指南检索 Agent。不能凭记忆回答，只能通过工具收集证据。

意图 → 工具：
- 页码/目录/章节 → lookup_toc | list_outline
- 故障/报警/异常 → search_chunks_batch（原因/原理/排查多路并行），补充用 search_chunks
- 参数规格 → search_chunks，filters.asset_types 含 table
- 片段不够或可能延续 → read_chunks | read_neighbor_chunks（锚点用 id=，勿用 [1][2]）
- 结果不足 → 换 query 或放宽 filters；勿重复相同调用
- 问题缺少关键信息且换 query 仍无法消歧 → ask_user（只问一点，勿猜测）
- 证据足够 → finish

可在 content 中简要说明推理，但必须通过 tool call 选择下一步。"""


def _build_system_prompt(lang: str) -> str:
    return "\n\n".join([_CORE_RULES, _LANG_DIRECTIVE.get(lang, _LANG_DIRECTIVE["zh"])])


def _question_label(lang: str) -> str:
    return "Question" if lang == "en" else "问题"


def _history_note(lang: str) -> str:
    if lang == "en":
        return (
            "\n\n(Prior turns are for reference only; answer ONLY the question "
            "below using this <context>.)"
        )
    return "\n\n（以上对话仅供理解指代；请仅根据本段 <context> 回答下列问题。）"


def _question_line(lang: str, question: str, chat_history: list | None) -> str:
    line = f"{_question_label(lang)}：{question}"
    if chat_history:
        line += _history_note(lang)
    return line


def _user_context_block(context: str, question_line: str) -> str:
    return f"<context>\n{context}\n</context>\n\n{question_line}"


class LLMService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = AsyncOpenAI(
            base_url=self.settings.llm_api_base_url,
            api_key=self.settings.llm_api_key,
        )

    def build_messages(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
        *,
        lang: str = "zh",
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _build_system_prompt(lang)}
        ]
        if chat_history:
            messages.extend(chat_history[-6:])
        messages.append(
            {
                "role": "user",
                "content": _user_context_block(
                    context, _question_line(lang, question, chat_history)
                ),
            }
        )
        return messages

    async def chat(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
        *,
        lang: str = "zh",
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(
                question,
                context,
                chat_history,
                lang=lang,
            ),
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _build_streamed_agent_message(
        content: str,
        reasoning_content: str,
        tool_calls_acc: dict[int, dict[str, Any]],
    ) -> Any:
        tool_calls_list = []
        for idx in sorted(tool_calls_acc):
            entry = tool_calls_acc[idx]
            tool_calls_list.append(
                SimpleNamespace(
                    id=entry.get("id") or "",
                    function=SimpleNamespace(
                        name=entry.get("name") or "",
                        arguments="".join(entry.get("arguments_parts", [])),
                    ),
                )
            )
        return SimpleNamespace(
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls_list or None,
        )

    async def decide_agent_action_stream(
        self, question: str, steps: list
    ) -> AsyncIterator[dict[str, Any]]:
        stream = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                *build_agent_messages(question, steps),
            ],
            tools=AGENT_TOOL_DEFINITIONS,
            temperature=0,
            stream=True,
        )

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_acc: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue

            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "delta", "field": "content", "delta": delta.content}

            reasoning = getattr(delta, "reasoning_content", None)
            if isinstance(reasoning, str) and reasoning:
                reasoning_parts.append(reasoning)
                yield {"type": "delta", "field": "reasoning", "delta": reasoning}

            if delta.tool_calls:
                for tool_call in delta.tool_calls:
                    idx = tool_call.index
                    entry = tool_calls_acc.setdefault(
                        idx,
                        {"id": "", "name": "", "arguments_parts": []},
                    )
                    if tool_call.id:
                        entry["id"] = tool_call.id
                    if tool_call.function:
                        if tool_call.function.name:
                            entry["name"] = tool_call.function.name
                        if tool_call.function.arguments:
                            entry["arguments_parts"].append(tool_call.function.arguments)

        message = self._build_streamed_agent_message(
            "".join(content_parts),
            "".join(reasoning_parts),
            tool_calls_acc,
        )
        yield {"type": "result", "payload": parse_agent_tool_response(message)}

    async def chat_stream(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
        *,
        lang: str = "zh",
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(
                question,
                context,
                chat_history,
                lang=lang,
            ),
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
