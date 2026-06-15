import json
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import Settings, get_settings

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

FILTER_EXTRACTION_PROMPT = """你是检索过滤器抽取器。根据用户问题，判断是否需要按说明书元数据缩小检索范围。

只输出 JSON 对象，不要输出其它文字。字段说明：
- chunk_types: 数组，取值仅限 text、procedure、warning、table；用户明确要步骤/警告/表格时填写，否则 null
- page_gte / page_lte: 整数，用户提到具体页码或页码范围时填写；单页则两者相同；否则 null
- section_prefix: 字符串，用户明确要某章节路径前缀时填写，否则 null
- section_contains: 字符串，用户提到章节/部分名称关键词时填写（如「安装」「第三章」「安全说明」），否则 null

规则：
- 仅抽取问题中明确表达的约束，不要猜测
- 普通知识问答、未限定章节/页码/内容类型时，所有字段都为 null
- 问操作步骤、安装方法、如何使用 → chunk_types 含 procedure
- 问警告、注意事项、危险说明 → chunk_types 含 warning
- 问参数表、规格表 → chunk_types 含 table
- 「第5页」「page 12」→ page_gte=page_lte=对应页码
- 「第3-10页」→ page_gte=3, page_lte=10
- 「安装章节」「关于安全部分」→ section_contains 填关键词

示例输出：
{"chunk_types": ["procedure"], "page_gte": null, "page_lte": null, "section_prefix": null, "section_contains": "安装"}
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

    async def extract_query_filters(self, question: str) -> dict:
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": FILTER_EXTRACTION_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        return payload if isinstance(payload, dict) else {}

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
