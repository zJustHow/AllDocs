from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, Literal

from openai import AsyncOpenAI

from app.config import Settings, get_settings
from app.services.vision_api import (
    vision_api_base_url,
    vision_api_key,
    vision_model_name,
)
from app.services.agent.tool_definitions import (
    AGENT_TOOL_DEFINITIONS,
    build_agent_messages,
    parse_agent_tool_response,
)
from app.services.vision_util import VisionImage

PromptMode = Literal["text", "embed", "vision"]

_CORE_RULES = """你是产品操作指南助手。仅依据 <context> 与当前问题作答，不得编造。

证据：<context> 中的片段、表格与图示均为系统从操作指南检索注入，非用户提供。
多轮：历史消息仅供理解指代；只答本轮问题，勿重复或改答历史问题。
结构：开放问答直接作答；操作类用有序列表；参数类准确引用原文。故障/排查类且 context 有相关信息时，中文可用「问题产生原因」「相关原理」「排查与解决步骤」，英文用 "Root cause" / "Background" / "Troubleshooting steps"；某类缺失则写明指南中未找到，不得编造。无法作答时明确说明未找到相关信息。
引用：每句或列表项末标 [n]（与 context 编号一致）；[n] 是来源编号非图号，勿写「见图 [n]」「对应图 [n]」；方括号内仅数字；多源写 [1][2]；正文只写 [n]，勿写 context/见 context/参见 [n]；禁止文末列「来源」「References」。示例：把主电源开关拨到 ON。[1]
格式：保留原文关键术语；数值范围用连字符（1-255、1.1-1.15），勿用波浪号；禁止 Markdown 删除线（~~文字~~），不适用内容直接改写。"""

_LANG_DIRECTIVE = {
    "zh": (
        "语言：全文中文（专有名词、型号、按钮标识如 ON/OFF 可保留英文；必要时附英文对照）。"
        "回答中勿出现 context 等英文系统术语。"
    ),
    "en": (
        "Language: Respond entirely in English (keep product terms and model numbers). "
        "Do not use Chinese connective phrases or the word context."
    ),
}

_EMBED_RULES = """插图：[N] 是 citation 编号（与 context 一致，非图号），{{embed:N}} 的 N 即该编号。需展示原表/原图时，在引用 [N] 的说明段前插入 {{embed:N}}；勿堆在回答开头；多节分别引用时各放对应节前。每图最多一次；禁止 base64、Markdown 图片或 HTML。
示例：额定参数如下：\n\n{{embed:2}}\n\n请确认电压在允许范围内。[2]"""

_MODE_SUFFIX = {
    "embed": (
        "context 中 (visual) 条目含系统检索到的表格或图示。"
        "纯文字段落、操作步骤等不需要插图；禁止为无关 [N] 插入 {{embed:N}}。"
    ),
    "vision": (
        "本轮已附带系统检索裁剪图，请读图理解后再作答。"
        "仅对已附带裁剪图的 [N] 插入 {{embed:N}}；未附带图片的 (visual) 条目只引用文字；"
        "纯文字或与问题无关时不插入 {{embed:N}}。"
    ),
}

AGENT_SYSTEM_PROMPT = """你是产品操作指南检索 Agent。不能凭记忆回答，只能通过工具收集证据。

意图 → 工具：
- 页码/目录/章节 → lookup_toc | list_outline
- 故障/报警/异常 → search_chunks_batch（原因/原理/排查多路并行），补充用 search_chunks
- 参数规格 → search_chunks，filters.asset_types 含 table
- 片段不够或可能延续 → read_chunks | read_neighbor_chunks（锚点用 id=，勿用 [1][2]）
- 结果不足 → 换 query 或放宽 filters；勿重复相同调用
- 证据足够 → finish

可在 content 中简要说明推理，但必须通过 tool call 选择下一步。"""


def _build_system_prompt(lang: str, *, mode: PromptMode = "text") -> str:
    parts = [_CORE_RULES, _LANG_DIRECTIVE.get(lang, _LANG_DIRECTIVE["zh"])]
    if mode in ("embed", "vision"):
        parts.append(_EMBED_RULES)
    if suffix := _MODE_SUFFIX.get(mode):
        parts.append(suffix)
    return "\n\n".join(parts)


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


def _vision_image_caption(lang: str, image: VisionImage) -> str:
    meta = f"{image.document_name} p.{image.page}, {image.asset_type}"
    if lang == "en":
        return (
            f"[Citation [{image.ref_index}] illustration ({meta}); "
            f"[{image.ref_index}] is a source number, not a figure number]"
        )
    return (
        f"【来源 [{image.ref_index}] 附图（{meta}）；"
        f"[{image.ref_index}] 为引用编号，非图号】"
    )


class LLMService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = AsyncOpenAI(
            base_url=self.settings.llm_api_base_url,
            api_key=self.settings.llm_api_key,
        )
        self.vision_client = AsyncOpenAI(
            base_url=vision_api_base_url(self.settings),
            api_key=vision_api_key(self.settings),
        )

    def build_messages(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
        *,
        include_embed_rules: bool = False,
        lang: str = "zh",
    ) -> list[dict[str, str]]:
        mode: PromptMode = "embed" if include_embed_rules else "text"
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _build_system_prompt(lang, mode=mode)}
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

    def _vision_system_prompt(self, lang: str = "zh") -> str:
        return _build_system_prompt(lang, mode="vision")

    def _vision_model(self) -> str:
        return vision_model_name(self.settings)

    def build_vision_messages(
        self,
        question: str,
        context: str,
        vision_images: list[VisionImage],
        chat_history: list[dict[str, str]] | None = None,
        *,
        lang: str = "zh",
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._vision_system_prompt(lang)}
        ]
        if chat_history:
            messages.extend(chat_history[-6:])

        user_parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _user_context_block(
                    context, _question_line(lang, question, chat_history)
                ),
            }
        ]
        for image in vision_images:
            user_parts.append(
                {
                    "type": "text",
                    "text": _vision_image_caption(lang, image),
                }
            )
            user_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.media_type};base64,{image.base64}",
                    },
                }
            )
        messages.append({"role": "user", "content": user_parts})
        return messages

    async def chat(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
        *,
        include_embed_rules: bool = False,
        lang: str = "zh",
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(
                question,
                context,
                chat_history,
                include_embed_rules=include_embed_rules,
                lang=lang,
            ),
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    async def chat_vision(
        self,
        question: str,
        context: str,
        vision_images: list[VisionImage],
        chat_history: list[dict[str, str]] | None = None,
        *,
        lang: str = "zh",
    ) -> str:
        response = await self.vision_client.chat.completions.create(
            model=self._vision_model(),
            messages=self.build_vision_messages(
                question, context, vision_images, chat_history, lang=lang
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
        """Stream agent planning deltas, then yield a final parsed action payload."""
        # Thinking/reasoning models reject tool_choice="required"; omit it and rely on
        # the system prompt. Multi-turn tool loops must pass reasoning_content back
        # (see build_agent_messages).
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
        include_embed_rules: bool = False,
        lang: str = "zh",
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(
                question,
                context,
                chat_history,
                include_embed_rules=include_embed_rules,
                lang=lang,
            ),
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def chat_stream_vision(
        self,
        question: str,
        context: str,
        vision_images: list[VisionImage],
        chat_history: list[dict[str, str]] | None = None,
        *,
        lang: str = "zh",
    ) -> AsyncIterator[str]:
        stream = await self.vision_client.chat.completions.create(
            model=self._vision_model(),
            messages=self.build_vision_messages(
                question, context, vision_images, chat_history, lang=lang
            ),
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
