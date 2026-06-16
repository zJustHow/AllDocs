"""OpenAI-compatible function definitions for the retrieval agent."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_CHUNK_FILTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
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
            "name": "list_outline",
            "description": "列出文档章节树（目录大纲）。适用于「有哪些章节」「目录结构」类问题。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_toc",
            "description": "查询章节起始/结束页码。适用于「第几章在哪一页」「某节从哪页开始」类问题。",
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
            "name": "search_chunks",
            "description": "单次语义 + 全文混合检索。适用于单点事实、参数规格等。",
            "parameters": {
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
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_chunks_batch",
            "description": (
                "并行多路检索（最多 4 路）。推荐用于故障/报警/异常等多角度问题，"
                "一次同时查原因、原理、排查步骤等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "searches": {
                        "type": "array",
                        "items": _SEARCH_ITEM_SCHEMA,
                        "minItems": 1,
                        "maxItems": 4,
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
            "name": "read_chunks",
            "description": (
                "精读指定 chunk 的完整内容。chunk_id 必须来自上一步检索结果中的 id= 字段（UUID），"
                "不要用 [1][2] 序号。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chunk_ids": {
                        "type": "array",
                        "items": {"type": "string", "format": "uuid"},
                        "minItems": 1,
                        "maxItems": 10,
                        "description": "要精读的 chunk UUID 列表",
                    },
                },
                "required": ["chunk_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "证据已足够，结束检索并进入回答阶段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "结束检索的简要原因",
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


def _tool_call_id(step_num: int) -> str:
    return f"call_step_{step_num}"


def build_agent_messages(question: str, steps: list) -> list[dict[str, Any]]:
    """Build chat messages with assistant tool_calls and tool results."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"用户问题：{question}"},
    ]
    for step in steps:
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": step.thought or None,
            "tool_calls": [
                {
                    "id": _tool_call_id(step.step),
                    "type": "function",
                    "function": {
                        "name": step.action,
                        "arguments": json.dumps(
                            step.action_input, ensure_ascii=False
                        ),
                    },
                }
            ],
        }
        if step.reasoning_content:
            assistant_message["reasoning_content"] = step.reasoning_content
        messages.append(assistant_message)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": _tool_call_id(step.step),
                "content": step.observation,
            }
        )
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
    """Normalize an assistant message into {thought, action, action_input}."""
    reasoning_content = _message_reasoning_content(message)
    thought = (message.content or "").strip()
    if not thought and reasoning_content:
        thought = reasoning_content
    tool_calls = message.tool_calls or []

    if tool_calls:
        call = tool_calls[0]
        action = (call.function.name or "").strip()
        action_input = _parse_tool_arguments(call.function.arguments)
        if len(tool_calls) > 1:
            logger.info(
                "Agent returned %d tool calls; using first: %s",
                len(tool_calls),
                action,
            )
        if action not in AGENT_TOOL_NAMES:
            logger.warning("Unknown agent tool: %s", action)
            return {
                "thought": thought,
                "reasoning_content": reasoning_content,
                "action": "finish",
                "action_input": {"reason": f"unknown tool: {action}"},
            }
        return {
            "thought": thought,
            "reasoning_content": reasoning_content,
            "action": action,
            "action_input": action_input,
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
