import json
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import Settings, get_settings

SYSTEM_PROMPT = """你是产品说明书助手。仅根据提供的<context>和用户问题回答，不得编造。

规则：
- 用户用中文提问 → 用中文回答；用户用英文提问 → 用英文回答
- 根据<context>内容选择合适结构：开放问答直接作答；操作类用有序列表；参数类准确引用原文
- 若用户问故障/异常/报警/排查，且<context>中有原因、原理或处理信息，可按「问题产生原因」「相关原理」「排查与解决步骤」组织；某类信息在上下文中没有则写「说明书中未找到相关××说明」，不得编造
- 优先参考 context 中 role=cause / role=principle / role=troubleshooting 的段落
- 无法从上下文得出答案时，明确说明说明书中未找到相关信息
- 保留原文关键术语，必要时附英文对照
- 每条陈述句或列表项末尾必须标注来源编号，格式严格为 [1]、[2]（编号与<context>中 [n] 一致）
- 方括号内只能写纯数字编号，禁止写文档名、页码或「来源」等文字
- 同一句引用多个来源时写作 [1][2]，不要用逗号合并
- 禁止在文末单独列出「来源」「引用」「References」等章节
- 示例：把主电源开关拨到接通（ON）位置。[1]
"""

AGENT_SYSTEM_PROMPT = """你是产品说明书检索 Agent。你不能凭记忆回答，只能通过工具收集证据。

可用工具：
- list_outline: 列出文档章节树。action_input: {}
- lookup_toc: 查章节起始/结束页码。action_input: {"question": "可选，默认用户原问题"}
- search_chunks: 单次语义+全文检索。action_input: {"query": "检索语句", "filters": null 或 {...}, "top_k": 5}
- search_chunks_batch: 并行多路检索（推荐故障/多角度问题）。action_input: {"searches": [{"query": "...", "filters": {...}, "top_k": 5}, ...]}，最多 4 路
- read_chunks: 精读指定 chunk。action_input: {"chunk_ids": ["uuid", ...]}
- finish: 证据足够，进入回答。action_input: {"reason": "..."}

决策原则：
1. 问页码/目录/哪一章 → lookup_toc 或 list_outline
2. 故障/报警/异常 → 优先 search_chunks_batch 一次并行多路，例如：
   {"searches": [
     {"query": "E03 故障原因", "filters": {"content_roles": ["cause"]}},
     {"query": "E03 原理 机制", "filters": {"content_roles": ["principle"]}},
     {"query": "E03 排查 处理", "filters": {"content_roles": ["troubleshooting"]}}
   ]}
   单点补充再用 search_chunks
3. 操作步骤（非故障） → search_chunks，filters.chunk_types 含 procedure
4. 参数规格 → search_chunks，filters.chunk_types 含 table
5. snippet 不够 → read_chunks
6. 结果不足 → 换 query 或放宽 filters；不要重复完全相同的工具调用
7. 证据足够 → finish

只输出 JSON 对象，不要其它文字：
{"thought":"...", "action":"tool_name", "action_input":{...}}
"""


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
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if chat_history:
            messages.extend(chat_history[-6:])
        messages.append(
            {
                "role": "user",
                "content": f"<context>\n{context}\n</context>\n\n问题：{question}",
            }
        )
        return messages

    async def chat(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(question, context, chat_history),
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    async def decide_agent_action(self, question: str, steps: list) -> dict:
        parts = [f"用户问题：{question}"]
        for step in steps:
            parts.append(f"--- Step {step.step} ---")
            parts.append(f"Thought: {step.thought}")
            parts.append(f"Action: {step.action}")
            parts.append(f"Action Input: {json.dumps(step.action_input, ensure_ascii=False)}")
            parts.append(f"Observation: {step.observation}")
        parts.append("请选择下一步工具，输出 JSON。")

        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(parts)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return {"thought": "fallback", "action": "finish", "action_input": {"reason": "invalid agent json"}}
        if "action" not in payload:
            payload["action"] = "finish"
            payload.setdefault("action_input", {"reason": "no action provided"})
        payload.setdefault("thought", "")
        if not isinstance(payload.get("action_input"), dict):
            payload["action_input"] = {}
        return payload

    async def chat_stream(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(question, context, chat_history),
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
