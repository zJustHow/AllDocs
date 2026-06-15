import json
import logging
import re

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.services.chunk_filter import ChunkFilter
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

ALLOWED_CHUNK_TYPES = frozenset({"text", "procedure", "warning", "table"})

_PAGE_SINGLE_RE = re.compile(
    r"(?:第\s*(\d+)\s*页|page\s*(\d+)|p\.\s*(\d+)|on\s+page\s+(\d+))",
    re.IGNORECASE,
)
_PAGE_RANGE_RE = re.compile(
    r"第\s*(\d+)\s*(?:[-~到至])\s*(\d+)\s*页",
    re.IGNORECASE,
)
_SECTION_QUOTED_RE = re.compile(r"[「“\"']([^」”\"']{2,40})[」”\"'](?:章|节|部分)?")
_SECTION_ABOUT_RE = re.compile(
    r"(?:关于|在|有关)\s*([^\s，,？?。!！]{2,30}?)(?:章|节|部分|章节|里|中)"
)
_SECTION_CHAPTER_RE = re.compile(r"(第[一二三四五六七八九十百千零两\d]+章)")
_PROCEDURE_RE = re.compile(
    r"(?:步骤|如何操作|怎么操作|怎么安装|如何安装|使用方法|操作流程|操作步骤|"
    r"how\s+to|installation\s+steps?|operating\s+procedure)",
    re.IGNORECASE,
)
_WARNING_RE = re.compile(r"(?:警告|注意|危险|warning|caution)", re.IGNORECASE)
_TABLE_RE = re.compile(r"(?:表格|参数表|规格表|table)", re.IGNORECASE)


def _first_group(match: re.Match[str]) -> str | None:
    for group in match.groups():
        if group:
            return group
    return None


def extract_filters_heuristic(question: str) -> ChunkFilter | None:
    text = question.strip()
    if not text:
        return None

    page_gte: int | None = None
    page_lte: int | None = None
    section_contains: str | None = None
    chunk_types: list[str] | None = None

    range_match = _PAGE_RANGE_RE.search(text)
    if range_match:
        start, end = int(range_match.group(1)), int(range_match.group(2))
        page_gte, page_lte = (start, end) if start <= end else (end, start)
    else:
        page_match = _PAGE_SINGLE_RE.search(text)
        if page_match:
            page_value = int(_first_group(page_match) or "0")
            if page_value > 0:
                page_gte = page_lte = page_value

    for pattern in (_SECTION_QUOTED_RE, _SECTION_ABOUT_RE, _SECTION_CHAPTER_RE):
        section_match = pattern.search(text)
        if section_match:
            section_contains = section_match.group(1).strip()
            break

    detected_types: list[str] = []
    if _PROCEDURE_RE.search(text):
        detected_types.append("procedure")
    if _WARNING_RE.search(text):
        detected_types.append("warning")
    if _TABLE_RE.search(text):
        detected_types.append("table")
    if detected_types:
        chunk_types = detected_types

    if not any([page_gte, page_lte, section_contains, chunk_types]):
        return None

    return ChunkFilter(
        chunk_types=chunk_types,
        page_gte=page_gte,
        page_lte=page_lte,
        section_contains=section_contains,
    )


def _sanitize_inferred_payload(payload: dict) -> ChunkFilter | None:
    chunk_types = payload.get("chunk_types")
    if chunk_types is not None:
        if not isinstance(chunk_types, list):
            chunk_types = None
        else:
            chunk_types = [value for value in chunk_types if value in ALLOWED_CHUNK_TYPES]
            if not chunk_types:
                chunk_types = None

    page_gte = payload.get("page_gte")
    page_lte = payload.get("page_lte")
    if page_gte is not None:
        page_gte = int(page_gte)
    if page_lte is not None:
        page_lte = int(page_lte)
    if page_gte is not None and page_lte is not None and page_gte > page_lte:
        page_gte, page_lte = page_lte, page_gte

    section_prefix = payload.get("section_prefix")
    section_contains = payload.get("section_contains")
    if isinstance(section_prefix, str):
        section_prefix = section_prefix.strip() or None
    else:
        section_prefix = None
    if isinstance(section_contains, str):
        section_contains = section_contains.strip() or None
    else:
        section_contains = None

    try:
        result = ChunkFilter(
            chunk_types=chunk_types,
            page_gte=page_gte,
            page_lte=page_lte,
            section_prefix=section_prefix,
            section_contains=section_contains,
        )
    except ValidationError:
        return None

    return result if result.has_constraints() else None


class FilterExtractionService:
    def __init__(self, settings: Settings | None = None, llm: LLMService | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or LLMService(self.settings)

    async def extract_llm(self, question: str) -> ChunkFilter | None:
        try:
            payload = await self.llm.extract_query_filters(question)
        except Exception:
            logger.warning("LLM filter extraction failed", exc_info=True)
            return None
        return _sanitize_inferred_payload(payload)

    async def extract(self, question: str) -> ChunkFilter | None:
        heuristic = extract_filters_heuristic(question)
        if not self.settings.rag_auto_filter_llm:
            return heuristic

        llm_filter = await self.extract_llm(question)
        return ChunkFilter.merge_inferred(heuristic, llm_filter)
