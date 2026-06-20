import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ResolvedSection:
    document_id: UUID
    document_name: str
    section_path: str
    title: str
    start_page: int
    end_page: int
    score: float


def _rank_toc_entries(
    documents: list[Document],
    question: str,
) -> list[tuple[float, Document, TocEntry, int]]:
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
    return ranked


def format_document_outline(document: Document) -> str | None:
    if not document.toc_entries:
        return None
    entries = toc_entries_from_dicts(document.toc_entries)
    lines = [f"《{document.name}》章节树："]
    for entry in entries[:80]:
        indent = "  " * max(entry.level - 1, 0)
        lines.append(
            f"{indent}- {entry.title} (p.{entry.start_page}-p.{entry.end_page})"
        )
    if len(entries) > 80:
        lines.append(f"  ... 共 {len(entries)} 条，已截断")
    return "\n".join(lines)


def format_documents_outline(documents: list[Document]) -> str:
    if not documents:
        return "未找到可用文档目录（可能 PDF 无书签，需重新处理文档）。"
    parts: list[str] = []
    for document in documents:
        outline = format_document_outline(document)
        if outline:
            parts.append(outline)
        else:
            parts.append(f"《{document.name}》：无书签目录")
    return "\n\n".join(parts)


def document_outline_to_chunk(document: Document) -> dict | None:
    text = format_document_outline(document)
    if not text:
        return None
    entries = toc_entries_from_dicts(document.toc_entries)
    start_page = entries[0].start_page if entries else 1
    return {
        "chunk_id": f"toc-outline:{document.id}",
        "document_id": str(document.id),
        "document_name": document.name,
        "page": start_page,
        "section": "目录",
        "score": 1.0,
        "snippet": f"文档目录 · {document.name}",
        "text": text,
    }


def outline_to_chunks(documents: list[Document]) -> list[dict]:
    chunks: list[dict] = []
    for document in documents:
        chunk = document_outline_to_chunk(document)
        if chunk is not None:
            chunks.append(chunk)
    return chunks


def _entry_to_chunk(document: Document, entry: TocEntry, index: int, score: float) -> dict:
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
        "score": score,
        "snippet": f"{entry.title} ··· 第 {entry.start_page} 页",
        "text": text,
    }


async def resolve_section(
    db: AsyncSession,
    question: str,
    doc_ids: list[UUID] | None,
    *,
    section: str | None = None,
    document_id: UUID | None = None,
) -> ResolvedSection | None:
    query_text = (section or question).strip()
    if not query_text:
        return None

    stmt = select(Document).where(Document.toc_entries.is_not(None))
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    elif doc_ids:
        stmt = stmt.where(Document.id.in_(doc_ids))
    result = await db.execute(stmt)
    documents = [doc for doc in result.scalars().all() if doc.toc_entries]
    if not documents:
        return None

    ranked = _rank_toc_entries(documents, query_text)
    if not ranked:
        return None

    score, document, entry, _index = ranked[0]
    return ResolvedSection(
        document_id=document.id,
        document_name=document.name,
        section_path=entry.path,
        title=entry.title,
        start_page=entry.start_page,
        end_page=entry.end_page,
        score=score,
    )


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

    ranked = _rank_toc_entries(documents, question)
    chunks: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for score, document, entry, index in ranked:
        key = (str(document.id), entry.path)
        if key in seen:
            continue
        seen.add(key)
        chunks.append(_entry_to_chunk(document, entry, index, score))
        if len(chunks) >= top_k:
            break
    return chunks
