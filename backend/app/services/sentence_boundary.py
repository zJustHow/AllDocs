"""Shared sentence-boundary rules for answer text (frontend + backend)."""

from __future__ import annotations

_SENTENCE_END_CHARS = frozenset("。！？.!?;:；")


def _is_numbered_list_marker_at(text: str, dot_index: int) -> bool:
    return (
        dot_index > 0
        and text[dot_index] == "."
        and text[dot_index - 1].isdigit()
    )


def _is_sentence_end_at(text: str, index: int) -> bool:
    char = text[index]
    if char not in _SENTENCE_END_CHARS:
        return False
    return not (char == "." and _is_numbered_list_marker_at(text, index))


def split_answer_text(answer: str) -> list[str]:
    """Split answer text into non-empty sentence parts (delimiters removed)."""
    answer = answer.strip()
    if not answer:
        return []

    parts: list[str] = []
    start = 0
    index = 0
    while index < len(answer):
        if _is_sentence_end_at(answer, index):
            part = answer[start : index + 1].strip()
            if part:
                parts.append(part)
            index += 1
            while index < len(answer) and answer[index] in " \t\n\r":
                index += 1
            start = index
            continue
        index += 1

    tail = answer[start:].strip()
    if tail:
        parts.append(tail)
    return parts if parts else [answer]
