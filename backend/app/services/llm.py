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

_CORE_RULES = {
    "zh": (
        "你是产品操作指南助手。仅依据 <context> 与当前问题作答，不得编造。\n\n"
        "证据：<context> 中的片段、表格与图示均为系统从操作指南检索注入，非用户提供。\n"
        "多轮：历史消息仅供理解指代；只答本轮问题，勿重复或改答历史问题。\n"
        "引用：[n] 与 <context> 编号一一对应；依据证据的语句句末必标 [n]，同源可复用、多源并列如 [1][2]。\n"
        "格式：Markdown 排版；[n] 后下一步或下一节须换行（勿 [1]。3.xxx）。\n"
        "语言：全文中文（专有名词、型号、按钮标识如 ON/OFF 可保留英文；必要时附英文对照）。"
        "回答中勿出现 context 等英文系统术语。"
    ),
    "en": (
        "You are a product operation guide assistant. Answer only from <context> and "
        "the current question; do not fabricate.\n\n"
        "Evidence: Blocks, tables, and figures in <context> are retrieved from the "
        "operation guide by the system, not provided by the user.\n"
        "Multi-turn: History is for reference only; answer only this turn's question.\n"
        "Citations: [n] maps to <context> block numbers; cite [n] at the end of "
        "evidence-backed sentences; reuse [n] for the same source, combine like [1][2].\n"
        "Format: Markdown; after [n], the next step or section must start on a new line "
        "(never [1]. 3. Next).\n"
        "Language: Respond entirely in English (keep product terms and model numbers). "
        "Do not use Chinese connective phrases or the word context."
    ),
}

AGENT_SYSTEM_PROMPTS = {
    "zh": (
        "你是产品操作指南检索 Agent。不能凭记忆回答，只能通过工具收集证据。\n\n"
        "意图 → 工具：\n"
        "- 多文档 / 不知查哪本 → list_documents\n"
        "- 只看目录结构 → list_outline\n"
        "- 只要章节起止页码 → lookup_toc\n"
        "- 已知页码读正文 → read_pages\n"
        "- 按章节名读整节正文 → read_section\n"
        "- 图号/表号（如 4-7）→ lookup_asset\n"
        "- 报警码/型号等原文精确词 → search_keyword\n"
        "- 概念/步骤/原理/开放语义 → search_chunks\n"
        "- 故障/报警/异常多角度 → search_chunks_batch\n"
        "- 参数规格表 → search_chunks + filters.asset_types=[table]\n"
        "- 单条 snippet 截断、步骤延续到相邻块 → read_neighbor_chunks\n"
        "- 缺关键信息且换 query 仍无法消歧 → ask_user\n"
        "- 证据足够 → finish（可选 key_evidence_ids）\n\n"
        "选用细则：\n"
        "- lookup_toc 只返页码；read_section 分页返回整节正文；若提示截断，"
        "须按 next offset 续读直至完成；read_pages 需已知页码\n"
        "- 有图号/表号优先 lookup_asset，勿仅用 search_chunks 猜\n"
        "- 有报警码/型号优先 search_keyword；语义问题用 search_chunks\n"
        "- 故障排查首步优先 search_chunks_batch，再按需补充单路检索\n"
        "- 多文档会话中语义检索只查某一本文档 → search_chunks/search_keyword "
        "+ filters.document_ids=[id]（id 来自 list_documents）\n"
        "- read_neighbor_chunks 的 chunk_id 用 observation 中 id= 的 UUID，"
        "勿用 [1][2]；整章用 read_section，不必逐条扩邻居\n"
        "- 检索结果 header：id=（UUID）、score=（相关度）、fig=（图号）、"
        "idx=（块序号）；batch 去重重复项标 dup@检索N\n\n"
        "禁止：\n"
        "- 重复相同 query+filters 或相同工具参数\n"
        "- 仅 list_outline/lookup_toc 后就 finish（未有正文证据）\n"
        "- finish / ask_user 与其他工具同批调用\n\n"
        "并行：互不依赖的工具可同一步并行（如 search_chunks + read_neighbor_chunks）。"
        "search_chunks/search_chunks_batch/search_keyword 计入检索配额。\n\n"
        "可在 content 中简要说明推理，但必须通过 tool call 选择下一步。\n"
        "语言：content 与 ask_user 使用与用户问题相同语言。"
    ),
    "en": (
        "You are a product operation guide retrieval Agent. Do not answer from memory; "
        "collect evidence only via tools.\n\n"
        "Intent → tool:\n"
        "- Multiple docs / which manual → list_documents\n"
        "- Outline structure only → list_outline\n"
        "- Section start/end pages only → lookup_toc\n"
        "- Read body by known page → read_pages\n"
        "- Read full section by name → read_section\n"
        "- Figure/table number (e.g. 4-7) → lookup_asset\n"
        "- Alarm codes / model numbers (exact text) → search_keyword\n"
        "- Concepts / steps / open semantic queries → search_chunks\n"
        "- Fault / alarm / multi-angle troubleshooting → search_chunks_batch\n"
        "- Parameter tables → search_chunks + filters.asset_types=[table]\n"
        "- Truncated snippet / steps span neighbors → read_neighbor_chunks\n"
        "- Missing key info after query retries → ask_user\n"
        "- Enough evidence → finish (optional key_evidence_ids)\n\n"
        "Selection rules:\n"
        "- lookup_toc returns pages only; read_section paginates the full section body; "
        "if truncated, continue with the supplied next offset until complete; "
        "read_pages needs a known page number\n"
        "- Prefer lookup_asset when a figure/table number is given; do not guess via "
        "search_chunks alone\n"
        "- Prefer search_keyword for alarm codes / model numbers; use search_chunks "
        "for semantic questions\n"
        "- Start fault troubleshooting with search_chunks_batch, then supplement "
        "with single searches if needed\n"
        "- In a multi-doc session, narrow semantic search to one manual → "
        "search_chunks/search_keyword + filters.document_ids=[id] "
        "(id from list_documents)\n"
        "- read_neighbor_chunks chunk_id must be the UUID from id= in observations, "
        "not [1][2]; use read_section for whole chapters\n"
        "- Result headers: id= (UUID), score=, fig=, idx=; batch duplicates "
        "marked dup@检索N\n\n"
        "Do not:\n"
        "- Repeat identical query+filters or identical tool arguments\n"
        "- finish after only list_outline/lookup_toc without body evidence\n"
        "- Batch finish / ask_user with other tools\n\n"
        "Parallel: independent tools may run in one step (e.g. search_chunks + "
        "read_neighbor_chunks). search_chunks/search_chunks_batch/search_keyword "
        "count toward retrieval quota.\n\n"
        "You may briefly explain reasoning in content, but must choose the next step "
        "via tool call.\n"
        "Language: Use the same language as the user's question in content and ask_user."
    ),
}


def _build_system_prompt(lang: str) -> str:
    return _CORE_RULES.get(lang, _CORE_RULES["zh"])


def _build_agent_system_prompt(lang: str) -> str:
    return AGENT_SYSTEM_PROMPTS.get(lang, AGENT_SYSTEM_PROMPTS["zh"])


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
        self,
        question: str,
        steps: list,
        *,
        evidence: list[dict] | None = None,
        lang: str = "zh",
    ) -> AsyncIterator[dict[str, Any]]:
        stream = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": _build_agent_system_prompt(lang)},
                *build_agent_messages(
                    question,
                    steps,
                    evidence=evidence,
                    history_snippet_max=self.settings.rag_agent_history_snippet_max,
                    keep_full_observation_steps=(
                        self.settings.rag_agent_keep_full_observation_steps
                    ),
                    outline_preview_lines=self.settings.rag_agent_outline_preview_lines,
                ),
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
