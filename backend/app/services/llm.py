import json
from collections.abc import AsyncIterator
from typing import Literal

from openai import AsyncOpenAI

from app.config import Settings, get_settings

QueryIntent = Literal["troubleshooting", "how_to", "spec", "general"]

SYSTEM_PROMPT = """你是产品说明书助手。仅根据提供的<context>回答，不得编造。

规则：
- 用户用中文提问 → 用中文回答；用户用英文提问 → 用英文回答
- 操作步骤使用有序列表
- 无法从上下文得出答案时，明确说明说明书中未找到相关信息
- 保留原文关键术语，必要时附英文对照
- 每条陈述句或列表项末尾必须标注来源编号，格式严格为 [1]、[2]（编号与<context>中 [n] 一致）
- 方括号内只能写纯数字编号，禁止写文档名、页码或「来源」等文字
- 同一句引用多个来源时写作 [1][2]，不要用逗号合并
- 禁止在文末单独列出「来源」「引用」「References」等章节
- 示例：把主电源开关拨到接通（ON）位置。[1]
"""

TROUBLESHOOTING_SYSTEM_PROMPT = """你是产品说明书故障诊断助手。仅根据提供的<context>回答，不得编造。

当用户问题涉及故障、异常、报错、报警、无法正常工作等情况时，必须严格按以下结构输出：

## 问题产生原因
- 列出上下文中支持的原因；可多条，按手册顺序或可能性排列
- 若上下文中没有原因说明，写：说明书中未找到相关原因说明

## 相关原理
- 解释现象背后的工作机制、触发条件、检测逻辑或相关参数
- 若上下文中没有原理说明，写：说明书中未找到相关原理说明

## 排查与解决步骤
- 使用有序列表，从简单检查到复杂处理
- 区分「检查项」与「修复/处理动作」
- 若上下文中没有排查步骤，写：说明书中未找到相关排查步骤

规则：
- 不得把排查步骤写进「原因」，不得把原理内容写进步骤列表
- 优先使用 slot=cause / slot=principle / slot=procedure 标记的上下文
- 用户用中文提问 → 用中文回答；用户用英文提问 → 用英文回答
- 每条陈述句或列表项末尾必须标注来源编号，格式严格为 [1]、[2]
- 方括号内只能写纯数字编号
- 禁止在文末单独列出「来源」「引用」「References」等章节
"""

QUERY_PLANNER_PROMPT = """你是检索查询规划器。根据用户问题，输出检索计划 JSON，用于从产品说明书中检索相关内容。

只输出 JSON 对象，不要输出其它文字。

字段说明：
- intent: 字符串，取值 troubleshooting | how_to | spec | general
  - troubleshooting: 故障、异常、报错、报警、无法××、怎么处理、为什么坏了
  - how_to: 安装、操作、使用步骤（非故障排查）
  - spec: 参数、规格、指标、表格
  - general: 其它开放问答
- symptom: 字符串或 null，故障/报警/异常的核心描述（如「E03报警」「不开机」）
- sub_queries: 数组，仅 intent=troubleshooting 时填写，必须含 cause/principle/procedure 三个 slot
  - slot: cause | principle | procedure
  - query: 用于向量/全文检索的查询语句（中文或英文，覆盖该槽位所需信息）
  - content_roles: 优先检索的内容角色，取值 cause | principle | troubleshooting | symptom | null
    - cause 槽位建议 ["cause", "symptom"]
    - principle 槽位建议 ["principle"]
    - procedure 槽位建议 ["troubleshooting"]，可同时含 procedure 类型 chunk
  - chunk_types: 可选，取值 text | procedure | warning | table | null
  - section_hints: 可选字符串数组，章节关键词（如「故障原因」「排查」），仅作辅助
- top_k_per_slot: 整数，troubleshooting 时每个槽位检索条数，建议 3
- apply_metadata_filters: 布尔值；troubleshooting 必须为 false；窄问题（明确页码/章节）为 true
- filters: 对象或 null，窄问题时填写：
  - chunk_types, content_roles, page_gte, page_lte, section_prefix, section_contains

规则：
- troubleshooting 时不要设置 filters 中的 page/section/chunk_types 限制（apply_metadata_filters=false）
- 普通开放问答：intent=general，sub_queries=[]，filters 全 null
- 「第5页」「第3-10页」→ apply_metadata_filters=true，填 page_gte/page_lte
- 「安装章节」→ section_contains
- 问参数表 → intent=spec，filters.chunk_types=["table"]

troubleshooting 示例：
{"intent":"troubleshooting","symptom":"E03报警","sub_queries":[{"slot":"cause","query":"E03 报警 故障原因 过流","content_roles":["cause","symptom"]},{"slot":"principle","query":"E03 过流保护 检测原理","content_roles":["principle"]},{"slot":"procedure","query":"E03 报警 排查 处理 复位","content_roles":["troubleshooting"],"chunk_types":["procedure","text"]}],"top_k_per_slot":3,"apply_metadata_filters":false,"filters":null}

general 示例：
{"intent":"general","symptom":null,"sub_queries":[],"top_k_per_slot":3,"apply_metadata_filters":false,"filters":null}
"""

AGENT_SYSTEM_PROMPT = """你是产品说明书检索 Agent。你不能凭记忆回答，只能通过工具收集证据。

可用工具：
- list_outline: 列出文档章节树。action_input: {}
- lookup_toc: 查章节起始/结束页码。action_input: {"question": "可选，默认用户原问题"}
- search_chunks: 语义+全文检索正文。action_input: {"query": "检索语句", "filters": null 或 {"chunk_types":["procedure"],"section_contains":"安装","page_gte":1,"page_lte":10}, "top_k": 5}
- search_troubleshooting: 故障排查（原因/原理/步骤）。action_input: {"question": "可选"}
- read_chunks: 精读指定 chunk。action_input: {"chunk_ids": ["uuid", ...]}
- finish: 证据足够，进入回答。action_input: {"reason": "..."}

决策原则：
1. 问页码/目录/哪一章 → lookup_toc 或 list_outline
2. 故障/报警/异常 → search_troubleshooting；不足再 search_chunks
3. 操作步骤 → search_chunks，filters.chunk_types 含 procedure
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

    def system_prompt_for_intent(self, intent: QueryIntent) -> str:
        if intent == "troubleshooting":
            return TROUBLESHOOTING_SYSTEM_PROMPT
        return SYSTEM_PROMPT

    def build_messages(
        self,
        question: str,
        context: str,
        chat_history: list[dict[str, str]] | None = None,
        intent: QueryIntent = "general",
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt_for_intent(intent)}
        ]
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
        intent: QueryIntent = "general",
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(question, context, chat_history, intent),
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    async def plan_query(self, question: str) -> dict:
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": QUERY_PLANNER_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        return payload if isinstance(payload, dict) else {}

    async def decide_agent_action(
        self,
        question: str,
        steps: list,
        planner_hint: dict | None = None,
    ) -> dict:
        parts = [f"用户问题：{question}"]
        if planner_hint:
            parts.append(
                "Planner 建议（可参考，不必照搬）："
                + json.dumps(planner_hint, ensure_ascii=False)
            )
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
        intent: QueryIntent = "general",
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=self.build_messages(question, context, chat_history, intent),
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
