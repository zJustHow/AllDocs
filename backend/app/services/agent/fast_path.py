"""Heuristic fast paths that skip the agent planning loop for obvious intents."""

from __future__ import annotations

import re

from app.services.toc_lookup import is_toc_navigation_question, is_toc_outline_question

_FAULT_RE = re.compile(
    r"(?:故障|报警|异常|排查|诊断|原因|原理|处理步骤|"
    r"alarm|fault|troubleshoot|error\s+code|"
    r"E\d{2,})",
    re.IGNORECASE,
)
_BATCH_HINT_RE = re.compile(
    r"(?:分别|对比|区别|哪些情况|多种|几个)",
    re.IGNORECASE,
)

_FAST_SEARCH_MAX_LEN = 200


def detect_fast_path(question: str) -> tuple[str, dict] | None:
    """Return (tool_name, action_input) when a single tool call is sufficient."""
    text = question.strip()
    if not text:
        return None

    if is_toc_outline_question(text):
        return "list_outline", {}

    if is_toc_navigation_question(text):
        return "lookup_toc", {"question": text}

    if _FAULT_RE.search(text) or _BATCH_HINT_RE.search(text):
        return None

    if len(text) > _FAST_SEARCH_MAX_LEN:
        return None

    return "search_chunks", {"query": text}
