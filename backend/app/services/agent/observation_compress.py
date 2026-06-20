"""Compress historical agent tool observations before LLM replanning."""

from __future__ import annotations

from app.services.agent.tools import _format_chunk_header

RETRIEVAL_ACTIONS = frozenset(
    {
        "search_chunks",
        "search_chunks_batch",
        "lookup_toc",
        "lookup_asset",
        "read_section",
        "read_pages",
        "read_neighbor_chunks",
    }
)
READ_ACTIONS = frozenset({"read_section", "read_pages", "read_neighbor_chunks"})


def build_evidence_index(evidence: list[dict]) -> str:
    if not evidence:
        return ""
    lines = [f"当前证据池 {len(evidence)} 条（较早检索 observation 已压缩）："]
    for index, chunk in enumerate(evidence, start=1):
        lines.append(_format_chunk_header(chunk, index=index))
    return "\n".join(lines)


def compress_observation(
    observation: str,
    *,
    action: str,
    is_recent: bool,
    history_snippet_max: int = 60,
    outline_preview_lines: int = 5,
    short_text_max: int = 200,
) -> str:
    if is_recent:
        return observation
    if action in {"finish", "ask_user"}:
        return observation
    if action == "list_outline":
        return _compress_outline(observation, outline_preview_lines)
    if action == "list_documents":
        return _compress_outline(observation, outline_preview_lines)
    if len(observation) <= short_text_max:
        return observation
    if action == "search_chunks_batch":
        return _compress_batch_observation(observation, history_snippet_max, action)
    if action in RETRIEVAL_ACTIONS:
        return _compress_retrieval_observation(
            observation,
            action,
            history_snippet_max,
            strip_snippet=action in READ_ACTIONS,
        )
    if len(observation) > short_text_max:
        return observation[:short_text_max] + "…（已截断）"
    return observation


def _compress_outline(text: str, preview_lines: int) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= preview_lines:
        return text
    omitted = len(lines) - preview_lines
    return (
        f"（历史步压缩 · list_outline · 共 {len(lines)} 行）\n"
        + "\n".join(lines[:preview_lines])
        + f"\n… 省略 {omitted} 行；需章节页码请 lookup_toc。"
    )


def _compress_retrieval_observation(
    text: str,
    action: str,
    snippet_max: int,
    *,
    strip_snippet: bool,
) -> str:
    parts = text.split("\n\n")
    if not parts:
        return text

    summary = parts[0].strip()
    blocks: list[str] = []
    for block in parts[1:]:
        lines = block.strip().split("\n", 1)
        if not lines:
            continue
        chunk_header = lines[0].strip()
        if strip_snippet or len(lines) == 1:
            blocks.append(chunk_header)
            continue
        snippet = lines[1].strip()
        if snippet_max > 0:
            snippet = snippet[:snippet_max]
        blocks.append(f"{chunk_header}\n{snippet}")

    if not blocks:
        clipped = summary[:300]
        return clipped + ("…" if len(summary) > 300 else "")

    prefix = f"（历史步压缩 · {action} · {len(blocks)} 条"
    if strip_snippet:
        prefix += " · 正文见证据池"
    prefix += "）\n"
    return prefix + summary + "\n\n" + "\n\n".join(blocks)


def _compress_batch_observation(text: str, snippet_max: int, action: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    chunk_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("并行检索"):
            out.append(stripped)
            continue
        if stripped.startswith("--- 检索"):
            out.append(stripped)
            continue
        if stripped == "（无结果）":
            out.append(stripped)
            continue
        if stripped.startswith("[") or stripped.startswith("  ["):
            out.append(line.rstrip())
            chunk_count += 1
            continue
        if snippet_max > 0:
            out.append("    " + stripped[:snippet_max])

    prefix = f"（历史步压缩 · {action} · {chunk_count} 条）\n"
    return prefix + "\n".join(out)
