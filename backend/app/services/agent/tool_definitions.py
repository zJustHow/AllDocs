"""OpenAI-compatible function definitions for the retrieval agent."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_CHUNK_FILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_ids": {
            "type": "array",
            "items": {"type": "string", "format": "uuid"},
            "description": (
                "限定检索文档（UUID 列表）；多文档会话中缩小到指定手册。"
                "须为 list_documents 返回的 id；未指定时使用会话已选全部文档。"
            ),
        },
        "asset_types": {
            "type": "array",
            "items": {"type": "string", "enum": ["table", "figure"]},
            "description": "限制含指定类型 asset 的 chunk，例如查参数规格时含 table",
        },
        "page_gte": {"type": "integer", "minimum": 1, "description": "起始页码（含）"},
        "page_lte": {"type": "integer", "minimum": 1, "description": "结束页码（含）"},
        "section_prefix": {"type": "string", "description": "章节标题前缀匹配"},
        "section_contains": {"type": "string", "description": "章节标题包含子串"},
    },
}

_SEARCH_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "检索语句"},
        "filters": {
            **_CHUNK_FILTER_SCHEMA,
            "nullable": True,
            "description": "可选过滤条件；null 表示不限",
        },
        "top_k": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "description": "返回条数，默认 5",
        },
    },
    "required": ["query"],
}

AGENT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": (
                "列出当前会话可用文档（名称、页数、id、status）。"
                "适用于多文档消歧、选择 document_id。"
                "勿用于查章节或检索正文。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_outline",
            "description": (
                "列出文档章节树（目录大纲）。"
                "适用于「有哪些章节」「目录结构」；只需看结构、不需页码时用。"
                "若需章节起止页码用 lookup_toc；若需读章节正文用 read_section。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_toc",
            "description": (
                "查询章节起始/结束页码，不返回正文。"
                "适用于「第几章在哪一页」「某节从哪页开始」。"
                "已知页码要读内容 → read_pages；要读整章正文 → read_section。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "可选；默认使用用户原问题",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pages",
            "description": (
                "按已知页码分页读取 chunk（按 chunk_index 排序），返回完整正文。"
                "适用于「第 N 页写了什么」；需已知具体页码。"
                "若结果提示已截断，必须使用返回的 next offset 继续读取。"
                "不知页码只知章节名 → lookup_toc 或 read_section；勿用语义检索代替按页阅读。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "单页页码（与 page_gte/page_lte 二选一）",
                    },
                    "page_gte": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "起始页码（含）",
                    },
                    "page_lte": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "结束页码（含）",
                    },
                    "document_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "可选；限定文档",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                        "description": "分页偏移；续读使用上次提示的 next offset",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_section",
            "description": (
                "按章节名匹配目录，分页读取该节页码范围内的 chunk，返回完整正文。"
                "适用于整章操作流程、本章所有报警码、整节参数表等。"
                "若结果提示已截断，必须使用返回的 next offset 继续读取，直至无更多 chunk。"
                "只需页码不需正文 → lookup_toc；已知单页 → read_pages；"
                "单点事实/跨节检索 → search_chunks。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "章节名或路径（可选；与 question 二选一）",
                    },
                    "question": {
                        "type": "string",
                        "description": "可选；默认使用用户原问题",
                    },
                    "document_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "可选；限定文档",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                        "description": "分页偏移；首次为 0，续读使用上次提示的 next offset",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_chunks",
            "description": (
                "单次语义 + 全文混合检索（向量+BM25+rerank）。"
                "适用于概念、操作步骤、故障现象、原理说明等开放语义问题。"
                "报警码/型号等精确字符串优先 search_keyword；已知图号 → lookup_asset；"
                "多角度故障排查优先 search_chunks_batch。勿重复相同 query+filters。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索语句；用具体关键词、型号、现象，避免过宽",
                    },
                    "filters": {
                        **_CHUNK_FILTER_SCHEMA,
                        "nullable": True,
                        "description": "可选过滤条件；null 表示不限",
                    },
                    "top_k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "返回条数，默认 5",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_keyword",
            "description": (
                "短语/关键词 BM25 全文检索，偏精确匹配。"
                "适用于报警码（E001）、型号、零件号等原文关键词。"
                "概念解释、操作步骤、故障原因等开放问题用 search_chunks；"
                "需 HYBRID_ENABLED。语义检索无果时可补充，勿与相同 query 重复调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "原文关键词或短语，如报警码、型号",
                    },
                    "filters": {
                        **_CHUNK_FILTER_SCHEMA,
                        "nullable": True,
                        "description": "可选过滤条件；null 表示不限",
                    },
                    "top_k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "返回条数，默认 5",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_chunks_batch",
            "description": (
                "并行多路语义检索（最多 3 路），每路独立 query 与 filters。"
                "推荐用于故障/报警/异常：同时查原因、现象、排查步骤、相关参数。"
                "单点简单问题用 search_chunks 即可；多路 query 应互不重复。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "searches": {
                        "type": "array",
                        "items": _SEARCH_ITEM_SCHEMA,
                        "minItems": 1,
                        "maxItems": 3,
                        "description": "多路检索配置，每路独立 query 与 filters",
                    },
                },
                "required": ["searches"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_asset",
            "description": (
                "按图号/表号精确查找插图、表格及其关联 chunk。"
                "适用于「图4-7是什么」「表2-1额定参数」；号格式如 4-7、表2-1。"
                "无图号的概念问题用 search_chunks；整节内容用 read_section。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "figure_number": {
                        "type": "string",
                        "description": "图号/表号，如 4-7、2-1",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["figure", "table"],
                        "description": "可选；限定 figure 或 table",
                    },
                    "document_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "可选；限定文档",
                    },
                },
                "required": ["figure_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_neighbor_chunks",
            "description": (
                "读取锚点 chunk 及其前后相邻块（按 chunk_index），返回完整正文。"
                "适用于单条 snippet 被截断、步骤/表格可能延续到相邻块。"
                "chunk_id 必须来自检索结果 observation 的 id=（UUID），勿用 [1][2] 序号。"
                "整章内容用 read_section；已知页码用 read_pages。检索命中 chunk 的合成正文已在证据池，"
                "仅当相邻块未在检索结果中时才需调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chunk_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "锚点 chunk UUID",
                    },
                    "before": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3,
                        "description": "读取锚点之前几块，默认 1",
                    },
                    "after": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3,
                        "description": "读取锚点之后几块，默认 1",
                    },
                },
                "required": ["chunk_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "向用户提出一个澄清问题并结束检索。"
                "仅在缺少关键信息（型号、报警码、功能模块、目标文档等），"
                "且已换 query 检索仍无法消歧时使用。只问一点，勿猜测或编造。"
                "尚有检索配额且可换关键词时，优先继续检索而非 ask_user。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "向用户提出的具体问题（只问一点）",
                    },
                    "reason": {
                        "type": "string",
                        "description": "为何需要澄清（供 trace 使用，不直接展示给用户）",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "证据已足够，结束检索并进入回答阶段。"
                "可选 key_evidence_ids：列出最关键 chunk 的 id=（UUID），合成时优先排序。"
                "证据不足、仅看过目录/页码、或尚未检索到相关正文时勿 finish。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "结束检索的简要原因",
                    },
                    "key_evidence_ids": {
                        "type": "array",
                        "items": {"type": "string", "format": "uuid"},
                        "maxItems": 10,
                        "description": (
                            "可选；最关键证据的 chunk UUID（来自检索结果 id=），"
                            "按重要性排序，最多 10 条"
                        ),
                    },
                },
                "required": ["reason"],
            },
        },
    },
]

AGENT_TOOL_NAMES = frozenset(
    tool["function"]["name"] for tool in AGENT_TOOL_DEFINITIONS
)


def _tool_call_id(step_num: int, index: int = 0) -> str:
    if index == 0:
        return f"call_step_{step_num}"
    return f"call_step_{step_num}_{index}"


def _step_tool_calls(step) -> list:
    if step.tool_calls:
        return step.tool_calls
    from app.services.agent.state import AgentToolCall

    return [
        AgentToolCall(
            action=step.action,
            action_input=step.action_input,
            observation=step.observation,
        )
    ]


def build_agent_messages(
    question: str,
    steps: list,
    *,
    evidence: list[dict] | None = None,
    history_snippet_max: int = 60,
    keep_full_observation_steps: int = 1,
    outline_preview_lines: int = 5,
) -> list[dict[str, Any]]:
    """Build chat messages with assistant tool_calls and tool results."""
    from app.services.agent.observation_compress import (
        build_evidence_index,
        compress_observation,
    )

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"用户问题：{question}"},
    ]
    total_steps = len(steps)
    keep_full = max(1, keep_full_observation_steps)

    for index, step in enumerate(steps):
        is_recent = index >= total_steps - keep_full
        tool_calls = _step_tool_calls(step)
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": step.thought or None,
            "tool_calls": [
                {
                    "id": call.tool_call_id or _tool_call_id(step.step, call_index),
                    "type": "function",
                    "function": {
                        "name": call.action,
                        "arguments": json.dumps(
                            call.action_input, ensure_ascii=False
                        ),
                    },
                }
                for call_index, call in enumerate(tool_calls)
            ],
        }
        if is_recent and step.reasoning_content:
            assistant_message["reasoning_content"] = step.reasoning_content
        messages.append(assistant_message)
        for call_index, call in enumerate(tool_calls):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.tool_call_id or _tool_call_id(
                        step.step, call_index
                    ),
                    "content": compress_observation(
                        call.observation,
                        action=call.action,
                        is_recent=is_recent,
                        history_snippet_max=history_snippet_max,
                        outline_preview_lines=outline_preview_lines,
                    ),
                }
            )

    if len(steps) >= 2 and evidence:
        evidence_index = build_evidence_index(evidence)
        if evidence_index:
            messages.append({"role": "user", "content": evidence_index})

    return messages


def _parse_tool_arguments(raw: str | None) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid tool call arguments JSON: %s", raw[:200])
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _message_reasoning_content(message: Any) -> str:
    raw = getattr(message, "reasoning_content", None)
    return raw.strip() if isinstance(raw, str) else ""


def parse_agent_tool_response(message: Any) -> dict[str, Any]:
    """Normalize an assistant message into agent action payload."""
    reasoning_content = _message_reasoning_content(message)
    thought = (message.content or "").strip()
    if not thought and reasoning_content:
        thought = reasoning_content
    tool_calls = message.tool_calls or []

    if tool_calls:
        actions: list[dict[str, Any]] = []
        for call in tool_calls:
            action = (call.function.name or "").strip()
            action_input = _parse_tool_arguments(call.function.arguments)
            if action not in AGENT_TOOL_NAMES:
                logger.warning("Unknown agent tool: %s", action)
                continue
            actions.append(
                {
                    "action": action,
                    "action_input": action_input,
                    "tool_call_id": getattr(call, "id", None) or "",
                }
            )

        if not actions:
            return {
                "thought": thought,
                "reasoning_content": reasoning_content,
                "actions": [],
                "action": "finish",
                "action_input": {"reason": "no valid tool calls"},
            }

        if len(actions) > 1:
            logger.info(
                "Agent returned %d tool calls: %s",
                len(actions),
                [item["action"] for item in actions],
            )

        primary = actions[0]
        return {
            "thought": thought,
            "reasoning_content": reasoning_content,
            "actions": actions,
            "action": primary["action"],
            "action_input": primary["action_input"],
        }

    if thought:
        return {
            "thought": thought,
            "reasoning_content": reasoning_content,
            "action": "finish",
            "action_input": {"reason": thought},
        }

    return {
        "thought": "fallback",
        "reasoning_content": reasoning_content,
        "action": "finish",
        "action_input": {"reason": "no tool call returned"},
    }
