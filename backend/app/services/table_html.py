"""Convert PPStructure HTML table output into markdown summaries."""

from __future__ import annotations

import re
from html import unescape

_TABLE_SUMMARY_MAX_CHARS = 4000
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", flags=re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", flags=re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_MD_ROW_RE = re.compile(r"^\s*\|")
_MD_SEPARATOR_RE = re.compile(r"^\|\s*[-:| ]+\|\s*$")


def _clean_cell(text: str) -> str:
    stripped = _TAG_RE.sub("", text)
    return unescape(stripped).strip().replace("\n", " ")


def parse_html_table(html: str) -> tuple[list[list[str]], int, int, int]:
    """Return rows, row_count, max_col_count, filled_cell_count."""
    rows: list[list[str]] = []
    filled_cells = 0
    max_cols = 0
    for row_html in _ROW_RE.findall(html or ""):
        cells = [_clean_cell(cell) for cell in _CELL_RE.findall(row_html)]
        if not cells:
            continue
        max_cols = max(max_cols, len(cells))
        filled_cells += sum(1 for cell in cells if cell)
        rows.append(cells)
    return rows, len(rows), max_cols, filled_cells


def rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    body = normalized[1:] if len(normalized) > 1 else []

    def _line(cells: list[str]) -> str:
        return "| " + " | ".join(cell or " " for cell in cells) + " |"

    lines = [_line(header)]
    if body:
        lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
        lines.extend(_line(row) for row in body)
    return "\n".join(lines)


def table_dimensions_meet_minimum(
    row_count: int,
    col_count: int,
    *,
    min_rows: int,
    min_cols: int,
) -> bool:
    """True when either dimension reaches its minimum (OR, not AND)."""
    return row_count >= min_rows or col_count >= min_cols


def html_table_to_markdown(html: str, *, max_chars: int = _TABLE_SUMMARY_MAX_CHARS) -> str:
    rows, _, _, _ = parse_html_table(html)
    if not rows:
        return ""
    return rows_to_markdown(rows)[:max_chars]


def parse_markdown_table(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not _MD_ROW_RE.match(stripped) or _MD_SEPARATOR_RE.match(stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def markdown_table_column_count(markdown: str) -> int:
    rows = parse_markdown_table(markdown)
    if not rows:
        return 0
    return max(len(row) for row in rows)


def merge_markdown_summaries(
    summaries: list[str],
    *,
    max_chars: int = _TABLE_SUMMARY_MAX_CHARS,
) -> str:
    merged_rows: list[list[str]] = []
    for index, summary in enumerate(summaries):
        rows = parse_markdown_table(summary)
        if not rows:
            continue
        if index == 0:
            merged_rows = rows
            continue
        start = 0
        if merged_rows and rows and rows[0] == merged_rows[0]:
            start = 1
        merged_rows.extend(rows[start:])
    if not merged_rows:
        return ""
    return rows_to_markdown(merged_rows)[:max_chars]
