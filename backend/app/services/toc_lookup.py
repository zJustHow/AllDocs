import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.services.ingestion import TocEntry, toc_entries_from_dicts

_CHAPTER_INDEX_RE = re.compile(r"第([一二三四五六七八九十百千零两\d]+)章")
_SECTION_TERM_RE = re.compile(
    r"[「“\"']([^」”\"']{2,40})[」”\"']|"
    r"(?:关于|有关)\s*([^\s，,？?。!！]{2,30}?)(?:章|节|部分|章节)"
)
_TOC_NAV_NOISE_RE = re.compile(
    r"(?:第几页|哪一页|哪页|从哪页|从第几页|页码|多少页|"
    r"目录|contents|table\s+of\s+contents|"
    r"在哪一页|在哪页|哪页开始|从.*页开始|"
    r"which\s+page|what\s+page|starts?\s+on\s+page|page\s+number|开始)",
    re.IGNORECASE,
)

_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_chapter_index(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        value = int(token)
        return value if value > 0 else None
    if token == "十":
        return 10
    if token.startswith("十") and len(token) == 2 and token[1] in _CN_DIGITS:
        return 10 + _CN_DIGITS[token[1]]
    if token.endswith("十") and len(token) == 2 and token[0] in _CN_DIGITS:
        return _CN_DIGITS[token[0]] * 10
    if len(token) == 1 and token in _CN_DIGITS:
        return _CN_DIGITS[token]
    return None


def extract_toc_query(question: str) -> tuple[int | None, list[str]]:
    """Return optional 1-based chapter index and free-text section terms."""
    text = question.strip()
    chapter_index: int | None = None
    chapter_match = _CHAPTER_INDEX_RE.search(text)
    if chapter_match:
        chapter_index = _parse_chapter_index(chapter_match.group(1))

    terms: list[str] = []
    if chapter_match:
        terms.append(chapter_match.group(0))

    for match in _SECTION_TERM_RE.finditer(text):
        term = match.group(1) or match.group(2)
        if term and term.strip():
            terms.append(term.strip())

    cleaned = _TOC_NAV_NOISE_RE.sub(" ", text)
    cleaned = _CHAPTER_INDEX_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,？?。!！")
    if len(cleaned) >= 2:
        terms.append(cleaned)

    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(term)
    return chapter_index, deduped


def _level_one_entries(entries: list[TocEntry]) -> list[TocEntry]:
    return [entry for entry in entries if entry.level == 1]


def _score_entry(
    entry: TocEntry,
    *,
    chapter_index: int | None,
    terms: list[str],
    level_one: list[TocEntry],
) -> float:
    if chapter_index is not None and level_one:
        try:
            indexed = level_one[chapter_index - 1]
            if indexed is entry:
                return 100.0
            if indexed.title == entry.title or indexed.path == entry.path:
                return 100.0
        except IndexError:
            pass

    haystack = f"{entry.title} {entry.path}".casefold()
    score = 0.0
    for term in terms:
        needle = term.casefold()
        if needle and needle in haystack:
            score += 10.0 + len(needle)
        if needle and needle in entry.title.casefold():
            score += 5.0

    if score == 0.0 and chapter_index is None and not terms:
        if entry.level == 1:
            return 1.0
        return 0.2 / entry.level
    return score


def _entry_to_citation(document: Document, entry: TocEntry, index: int, score: float) -> dict:
    text = (
        f"章节：{entry.path}\n"
        f"起始页：第 {entry.start_page} 页\n"
        f"结束页：第 {entry.end_page} 页"
    )
    return {
        "chunk_id": f"toc:{document.id}:{index}",
        "document_id": str(document.id),
        "document_name": document.name,
        "page": entry.start_page,
        "section": entry.path,
        "content_role": None,
        "score": score,
        "snippet": f"{entry.title} ··· 第 {entry.start_page} 页",
        "text": text,
    }


async def lookup_toc(
    db: AsyncSession,
    question: str,
    doc_ids: list[UUID] | None,
    *,
    top_k: int = 5,
) -> list[dict]:
    stmt = select(Document).where(Document.toc_entries.is_not(None))
    if doc_ids:
        stmt = stmt.where(Document.id.in_(doc_ids))
    result = await db.execute(stmt)
    documents = [doc for doc in result.scalars().all() if doc.toc_entries]

    if not documents:
        return []

    chapter_index, terms = extract_toc_query(question)
    ranked: list[tuple[float, Document, TocEntry, int]] = []

    for document in documents:
        entries = toc_entries_from_dicts(document.toc_entries)
        level_one = _level_one_entries(entries)
        for index, entry in enumerate(entries):
            score = _score_entry(
                entry,
                chapter_index=chapter_index,
                terms=terms,
                level_one=level_one,
            )
            if score <= 0:
                continue
            ranked.append((score, document, entry, index))

    ranked.sort(key=lambda item: item[0], reverse=True)
    citations: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for score, document, entry, index in ranked:
        key = (str(document.id), entry.path)
        if key in seen:
            continue
        seen.add(key)
        citations.append(_entry_to_citation(document, entry, index, score))
        if len(citations) >= top_k:
            break
    return citations
