from collections.abc import AsyncIterator
from typing import Any

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

SYSTEM_PROMPT = """你是产品操作指南助手。仅根据提供的<context>和用户问题回答，不得编造。

规则：
- 用户用中文提问 → 用中文回答；用户用英文提问 → 用英文回答
- 根据<context>内容选择合适结构：开放问答直接作答；操作类用有序列表；参数类准确引用原文
- 若用户问故障/异常/报警/排查，且<context>中有原因、原理或处理信息，可按「问题产生原因」「相关原理」「排查与解决步骤」组织；某类信息在上下文中没有则写「操作指南中未找到相关××说明」，不得编造
- 无法从上下文得出答案时，明确说明操作指南中未找到相关信息
- 保留原文关键术语，必要时附英文对照
- 每条陈述句或列表项末尾必须标注来源编号，格式严格为 [1]、[2]（编号与<context>中 [n] 一致）
- 方括号内只能写纯数字编号，禁止写文档名、页码或「来源」等文字
- 同一句引用多个来源时写作 [1][2]，不要用逗号合并
- 禁止在文末单独列出「来源」「引用」「References」等章节
- 示例：把主电源开关拨到接通（ON）位置。[1]
"""

VISION_EXTRA_RULES = """
- 用户消息中附带了部分条目的表格/图示裁剪图，请读图理解后再作答
- 当回答引用对应 [N] 且用户需要看到原表/原图时，插入 {{embed:N}}（N 与 [N] 一致）
- 纯文字段落或图片与问题无关时，禁止插入 {{embed:N}}
- 每张图片在回答中最多出现一次；禁止输出 base64、Markdown 图片语法或 HTML
- 示例（参数类问题）：额定参数如下：\n\n{{embed:2}}\n\n请确认电压在允许范围内。[2]
"""

EMBED_RULES = """
- <context> 中标记 (visual) 的条目含表格或图示裁剪图；当回答引用该条目 [N] 且用户需要看到原表/原图时，用 {{embed:N}} 插入（N 与 [N] 一致）
- 纯文字段落、操作步骤等不需要插图；禁止为无关 [N] 插入 {{embed:N}}
- 每张图片在回答中最多出现一次；禁止输出 base64、Markdown 图片语法或 HTML
- 示例（参数类问题）：额定参数如下：\n\n{{embed:2}}\n\n请确认电压在允许范围内。[2]
"""

AGENT_SYSTEM_PROMPT = """你是产品操作指南检索 Agent。你不能凭记忆回答，只能通过工具收集证据。

决策原则：
1. 问页码/目录/哪一章 → lookup_toc 或 list_outline
2. 故障/报警/异常 → 优先 search_chunks_batch 一次并行多路（原因、原理、排查各一路），单点补充再用 search_chunks
3. 参数规格 → search_chunks，filters.asset_types 含 table
4. snippet 不够 → read_chunks（chunk_id 用检索结果 id= 字段，不要用 [1][2] 序号）
5. 结果不足 → 换 query 或放宽 filters；不要重复完全相同的工具调用
6. 证据足够 → 调用 finish

可在 content 中简要说明推理过程，但必须通过 tool call 选择下一步工具。
"""


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
    ) -> list[dict[str, str]]:
        system_prompt = SYSTEM_PROMPT
        if include_embed_rules:
            system_prompt += EMBED_RULES
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if chat_history:
            messages.extend(chat_history[-6:])
        messages.append(
            {
                "role": "user",
                "content": f"<context>\n{context}\n</context>\n\n问题：{question}",
            }
        )
        return messages

    def _vision_system_prompt(self) -> str:
        return SYSTEM_PROMPT + VISION_EXTRA_RULES

    def _vision_model(self) -> str:
        return vision_model_name(self.settings)

    def build_vision_messages(
        self,
        question: str,
        context: str,
        vision_images: list[VisionImage],
        chat_history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._vision_system_prompt()}
        ]
        if chat_history:
            messages.extend(chat_history[-6:])

        user_parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": f"<context>\n{context}\n</context>\n\n问题：{question}",
            }
        ]
        for image in vision_images:
            user_parts.append(
                {
                    "type": "text",
                    "text": (
                        f"上图对应 context [{image.ref_index}] "
                        f"（{image.document_name} p.{image.page}，type={image.asset_type}）"
                    ),
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
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(
                question, context, chat_history, include_embed_rules=include_embed_rules
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
    ) -> str:
        response = await self.vision_client.chat.completions.create(
            model=self._vision_model(),
            messages=self.build_vision_messages(
                question, context, vision_images, chat_history
            ),
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    async def decide_agent_action(self, question: str, steps: list) -> dict:
        # Thinking/reasoning models reject tool_choice="required"; omit it and rely on
        # the system prompt. Multi-turn tool loops must pass reasoning_content back
        # (see build_agent_messages).
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                *build_agent_messages(question, steps),
            ],
            tools=AGENT_TOOL_DEFINITIONS,
            temperature=0,
        )
        return parse_agent_tool_response(response.choices[0].message)

    async def chat_stream(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
        *,
        include_embed_rules: bool = False,
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(
                question, context, chat_history, include_embed_rules=include_embed_rules
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
    ) -> AsyncIterator[str]:
        stream = await self.vision_client.chat.completions.create(
            model=self._vision_model(),
            messages=self.build_vision_messages(
                question, context, vision_images, chat_history
            ),
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
