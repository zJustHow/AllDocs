"""PDF table-of-contents parsing and section resolution."""

from __future__ import annotations

import re

import fitz

from app.services.pdf_toc_types import TocAnchor, TocEntry

_SECTION_PATH_MAX_LEN = 512
_SECTION_PATH_SEPARATOR = " > "
_CHAPTER_ONE_RE = re.compile(
    r"第[一1壹]章|chapter\s*1\b",
    re.IGNORECASE,
)
_CHAPTER_TITLE_RE = re.compile(
    r"第[一二三四五六七八九十百千零两\d]+章|chapter\s+\d+",
    re.IGNORECASE,
)


def _truncate_section_path(path: str) -> str:
    if len(path) <= _SECTION_PATH_MAX_LEN:
        return path
    return path[: _SECTION_PATH_MAX_LEN - 1] + "…"


def _dest_raw_point(dest: dict) -> tuple[float, float] | None:
    to = dest.get("to")
    if to is None:
        return None
    try:
        if hasattr(to, "x"):
            return float(to.x), float(to.y)
        return float(to[0]), float(to[1])
    except (TypeError, ValueError, IndexError):
        return None


def _dest_y_from_pdf_space(page: fitz.Page, raw_x: float, raw_y: float) -> float:
    pdf_point = fitz.Point(raw_x, raw_y)
    return float((pdf_point * page.transformation_matrix).y)


def _count_non_decreasing(values: list[float]) -> int:
    if len(values) < 2:
        return 0
    return sum(1 for index in range(len(values) - 1) if values[index] <= values[index + 1])


def _toc_dest_coordinate_votes(page: fitz.Page, raw_ys: list[float]) -> tuple[int, int]:
    """Score top-down vs PDF-space interpretation for one page's bookmark Y values."""
    if not raw_ys:
        return 0, 0

    page_height = float(page.rect.height)
    flipped_ys = [_dest_y_from_pdf_space(page, 0.0, raw_y) for raw_y in raw_ys]
    top_down_votes = _count_non_decreasing(raw_ys)
    pdf_votes = _count_non_decreasing(flipped_ys)

    if len(raw_ys) == 1:
        raw_y = raw_ys[0]
        flipped_y = flipped_ys[0]
        near_top_raw = raw_y <= page_height * 0.45
        near_bottom_flipped = flipped_y >= page_height * 0.55
        near_top_flipped = flipped_y <= page_height * 0.45
        near_bottom_raw = raw_y >= page_height * 0.55
        if near_top_raw and near_bottom_flipped:
            top_down_votes += 1
        elif near_top_flipped and near_bottom_raw:
            pdf_votes += 1

    return top_down_votes, pdf_votes


def _document_toc_dest_already_top_down(
    doc: fitz.Document,
    page_raw_ys: dict[int, list[float]],
) -> bool:
    top_down_total = 0
    pdf_total = 0
    for page_num, raw_ys in page_raw_ys.items():
        top_down_votes, pdf_votes = _toc_dest_coordinate_votes(doc[page_num - 1], raw_ys)
        top_down_total += top_down_votes
        pdf_total += pdf_votes
    if top_down_total != pdf_total:
        return top_down_total > pdf_total
    return False


def _dest_to_page_y(
    page: fitz.Page,
    dest: dict,
    *,
    already_top_down: bool = False,
) -> float | None:
    point = _dest_raw_point(dest)
    if point is None:
        return None
    raw_x, raw_y = point
    if already_top_down:
        return raw_y
    return _dest_y_from_pdf_space(page, raw_x, raw_y)


def _parse_raw_toc(doc: fitz.Document) -> list[tuple[int, str, int, float | None]]:
    raw_toc = doc.get_toc(simple=False)
    if not raw_toc:
        return []

    page_raw_ys: dict[int, list[float]] = {}
    pending_rows: list[tuple[int, str, int, dict | None, float | None]] = []

    for row in raw_toc:
        level = int(row[0])
        title = str(row[1]).strip()
        page = max(1, int(row[2]))
        dest = row[3] if len(row) > 3 else None
        raw_y: float | None = None
        if isinstance(dest, dict):
            dest_page = dest.get("page")
            if dest_page is not None and int(dest_page) >= 0:
                page = int(dest_page) + 1
            if 1 <= page <= doc.page_count:
                point = _dest_raw_point(dest)
                if point is not None:
                    raw_y = point[1]
                    page_raw_ys.setdefault(page, []).append(raw_y)
        pending_rows.append((level, title, page, dest, raw_y))

    document_already_top_down = _document_toc_dest_already_top_down(doc, page_raw_ys)

    parsed: list[tuple[int, str, int, float | None]] = []
    for level, title, page, dest, raw_y in pending_rows:
        y: float | None = None
        if isinstance(dest, dict) and raw_y is not None and 1 <= page <= doc.page_count:
            y = _dest_to_page_y(
                doc[page - 1],
                dest,
                already_top_down=document_already_top_down,
            )
        parsed.append((level, title, page, y))
    return parsed


class _SectionPathStack:
    __slots__ = ("_path_levels", "_path_titles")

    def __init__(self) -> None:
        self._path_titles: list[str] = []
        self._path_levels: list[int] = []

    def push(self, level: int, title: str) -> str:
        while self._path_levels and self._path_levels[-1] >= level:
            self._path_levels.pop()
            self._path_titles.pop()
        self._path_titles.append(title)
        self._path_levels.append(level)
        return _truncate_section_path(_SECTION_PATH_SEPARATOR.join(self._path_titles))

    def current(self) -> str | None:
        if not self._path_titles:
            return None
        return _truncate_section_path(_SECTION_PATH_SEPARATOR.join(self._path_titles))


def _build_toc_paths(
    parsed: list[tuple[int, str, int, float | None]],
) -> list[tuple[int, str, int, float | None, str]]:
    stack = _SectionPathStack()
    with_paths: list[tuple[int, str, int, float | None, str]] = []
    for level, title, page, y in parsed:
        path = stack.push(level, title)
        with_paths.append((level, title, page, y, path))
    return with_paths


def _toc_anchors_from_parsed(
    parsed: list[tuple[int, str, int, float | None]],
) -> list[TocAnchor]:
    if not parsed:
        return []

    anchors: list[TocAnchor] = []
    for level, title, page, y, path in _build_toc_paths(parsed):
        anchors.append(
            TocAnchor(
                level=level,
                title=title,
                path=path,
                page=page,
                y=y if y is not None else 0.0,
                has_y=y is not None,
            )
        )
    return sorted(anchors, key=lambda anchor: (anchor.page, anchor.y, anchor.level))


def _toc_entries_from_parsed(
    parsed: list[tuple[int, str, int, float | None]],
    page_count: int,
) -> list[TocEntry]:
    if not parsed:
        return []

    normalized: list[tuple[int, str, int, int]] = []
    for index, (level, title, page, _y) in enumerate(parsed):
        start_page = max(1, int(page))
        end_page = page_count
        for next_index in range(index + 1, len(parsed)):
            next_level, _, next_page, _ = parsed[next_index]
            if next_level <= level:
                end_page = max(start_page, int(next_page) - 1)
                break
        normalized.append((int(level), title, start_page, end_page))

    path_stack = _SectionPathStack()
    entries: list[TocEntry] = []
    for level, title, start_page, end_page in normalized:
        path = path_stack.push(level, title)
        entries.append(
            TocEntry(
                level=level,
                title=title,
                start_page=start_page,
                end_page=end_page,
                path=path,
            )
        )
    return entries


def parse_pdf_toc(doc: fitz.Document) -> tuple[list[TocEntry], list[TocAnchor]]:
    parsed = _parse_raw_toc(doc)
    if not parsed:
        return [], []
    return (
        _toc_entries_from_parsed(parsed, doc.page_count),
        _toc_anchors_from_parsed(parsed),
    )


def section_at_position(anchors: list[TocAnchor], page: int, y: float) -> str | None:
    stack = _SectionPathStack()
    for anchor in anchors:
        if (anchor.page, anchor.y) > (page, y):
            break
        stack.push(anchor.level, anchor.title)
    return stack.current()


def section_for_page(entries: list[TocEntry], page: int) -> str | None:
    matches = [entry for entry in entries if entry.start_page <= page <= entry.end_page]
    if not matches:
        return None
    return max(matches, key=lambda entry: entry.level).path


def first_chapter_start_page(entries: list[TocEntry]) -> int | None:
    if not entries:
        return None

    for entry in entries:
        if _CHAPTER_ONE_RE.search(entry.title) or _CHAPTER_ONE_RE.search(entry.path):
            return entry.start_page

    level_one = [entry for entry in entries if entry.level == 1]
    for entry in level_one:
        if _CHAPTER_TITLE_RE.search(entry.title):
            return entry.start_page

    if level_one:
        return min(entry.start_page for entry in level_one)

    return min(entry.start_page for entry in entries)


def should_skip_front_matter(page: int, toc_entries: list[TocEntry]) -> bool:
    content_start = first_chapter_start_page(toc_entries)
    return content_start is not None and page < content_start
