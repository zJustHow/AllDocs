import asyncio
import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.db.session import async_session_factory
from app.services.asset_lookup import lookup_asset
from app.services.chunk_filter import ChunkFilter
from app.services.chunk_format import format_chunk_header
from app.services.rag import RAGService
from app.services.toc_lookup import format_documents_outline, lookup_toc, outline_to_chunks

RETRIEVAL_QUOTA_MESSAGE = (
    "检索次数已达上限，无法继续 search_chunks/search_chunks_batch/search_keyword。"
    "可读取相邻片段（read_neighbor_chunks），"
    "证据足够时再 finish。"
)


async def _load_session_documents(
    db: AsyncSession,
    doc_ids: list[UUID] | None,
    *,
    order_by_name: bool = False,
) -> list[Document]:
    stmt = select(Document)
    if doc_ids:
        stmt = stmt.where(Document.id.in_(doc_ids))
    if order_by_name:
        stmt = stmt.order_by(Document.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


RETRIEVAL_TOOLS = frozenset({"search_chunks", "search_chunks_batch", "search_keyword"})
SEARCH_SNIPPET_MAX = 240
BATCH_SNIPPET_MAX = 160
NEIGHBOR_READ_MAX = 3
PAGE_READ_MAX_CHUNKS = 30
LOOKUP_ASSET_MAX = 5


FINISH_KEY_EVIDENCE_MAX = 10


def parse_finish_key_evidence_ids(action_input: dict) -> list[str]:
    raw = action_input.get("key_evidence_ids")
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        ids.append(text)
        if len(ids) >= FINISH_KEY_EVIDENCE_MAX:
            break
    return ids


def prioritize_evidence(
    evidence: list[dict],
    key_evidence_ids: list[str],
) -> list[dict]:
    """Put agent-selected chunk ids first; append remaining evidence in original order."""
    if not evidence or not key_evidence_ids:
        return evidence

    from app.services.chunk_loader import parse_chunk_uuids

    valid_ids, _invalid = parse_chunk_uuids(key_evidence_ids)
    if not valid_ids:
        return evidence

    by_id = {
        str(chunk.get("chunk_id")): chunk
        for chunk in evidence
        if chunk.get("chunk_id")
    }
    prioritized: list[dict] = []
    seen: set[str] = set()
    for chunk_id in valid_ids:
        key = str(chunk_id)
        chunk = by_id.get(key)
        if chunk is None or key in seen:
            continue
        seen.add(key)
        prioritized.append(chunk)

    for chunk in evidence:
        key = str(chunk.get("chunk_id") or "")
        if key and key in seen:
            continue
        prioritized.append(chunk)

    return prioritized or evidence


def _evidence_key(chunk: dict) -> str:
    chunk_id = chunk.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    return (
        f"{chunk.get('document_id')}:{chunk.get('page')}:"
        f"{chunk.get('section') or ''}"
    )


def _format_chunk_body(
    item: dict,
    *,
    full_text: bool = False,
    snippet_max: int = SEARCH_SNIPPET_MAX,
) -> str:
    if full_text:
        return item.get("text") or item.get("snippet") or ""
    body = item.get("snippet") or item.get("text") or ""
    return body[:snippet_max] if snippet_max > 0 else body


def _format_chunks(
    chunks: list[dict],
    *,
    source_tool: str,
    full_text: bool = False,
    snippet_max: int = SEARCH_SNIPPET_MAX,
) -> str:
    if not chunks:
        return "未检索到相关内容。"

    lines = [f"检索工具：{source_tool}，命中 {len(chunks)} 条："]
    for index, item in enumerate(chunks, start=1):
        header = format_chunk_header(item, index=index, detailed=True)
        body = _format_chunk_body(
            item,
            full_text=full_text,
            snippet_max=snippet_max,
        )
        lines.append(f"{header}\n{body}")
    return "\n\n".join(lines)


def _merge_batch_chunks(results: list[tuple[str, list[dict]]]) -> list[dict]:
    """Merge batch search hits in first-seen order, keeping the highest score per chunk."""
    merged_by_key: dict[str, dict] = {}
    order: list[str] = []
    for _, chunks in results:
        for chunk in chunks:
            key = _evidence_key(chunk)
            if key not in merged_by_key:
                merged_by_key[key] = dict(chunk)
                order.append(key)
                continue
            existing_score = float(merged_by_key[key].get("score") or 0.0)
            new_score = float(chunk.get("score") or 0.0)
            if new_score > existing_score:
                merged_by_key[key] = dict(chunk)
    return [merged_by_key[key] for key in order]


def _annotate_batch_duplicates(
    results: list[tuple[str, list[dict]]],
) -> tuple[list[tuple[str, list[tuple[dict, int | None]]]], int, int]:
    """Return per-branch hits with optional first-search index for duplicates."""
    first_seen: dict[str, int] = {}
    annotated: list[tuple[str, list[tuple[dict, int | None]]]] = []
    raw_total = 0

    for search_index, (query, chunks) in enumerate(results, start=1):
        branch: list[tuple[dict, int | None]] = []
        for chunk in chunks:
            raw_total += 1
            key = _evidence_key(chunk)
            if key in first_seen:
                branch.append((chunk, first_seen[key]))
                continue
            first_seen[key] = search_index
            branch.append((chunk, None))
        annotated.append((query, branch))

    return annotated, raw_total, len(first_seen)


def _format_batch_observation(results: list[tuple[str, list[dict]]]) -> str:
    if not results:
        return "search_chunks_batch 需要非空 searches 列表。"

    annotated, raw_total, unique_total = _annotate_batch_duplicates(results)
    if raw_total == unique_total:
        summary = f"并行检索 {len(results)} 路，合计命中 {raw_total} 条："
    else:
        summary = (
            f"并行检索 {len(results)} 路，合计命中 {raw_total} 条"
            f"（去重后 {unique_total} 条）："
        )
    lines = [summary]
    for index, (query, chunks) in enumerate(annotated, start=1):
        lines.append(f"\n--- 检索 {index}：{query} · 命中 {len(chunks)} 条 ---")
        if not chunks:
            lines.append("（无结果）")
            continue
        for hit, (item, dup_of) in enumerate(chunks, start=1):
            header = format_chunk_header(item, index=hit, indent="  ", detailed=True)
            if dup_of is not None:
                lines.append(f"{header} dup@检索{dup_of}")
                continue
            body = _format_chunk_body(item, snippet_max=BATCH_SNIPPET_MAX)
            lines.append(f"{header}\n    {body}")
    return "\n".join(lines)


def format_documents_list(documents: list[Document]) -> str:
    if not documents:
        return "当前会话无可用文档。"
    lines = [f"会话内文档 {len(documents)} 份："]
    for index, document in enumerate(documents, start=1):
        line = f"[{index}] {document.name} id={document.id}"
        if document.page_count is not None:
            line += f" pages={document.page_count}"
        line += f" status={document.status.value}"
        lines.append(line)
    return "\n".join(lines)


def _parse_optional_uuid(raw: object) -> UUID | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return UUID(text)
    except ValueError:
        return None


def merge_chunks_into_evidence(
    evidence: list[dict],
    seen_keys: set[str],
    chunks: list[dict],
    *,
    source_action: str | None = None,
) -> None:
    mark_semantic = source_action in RETRIEVAL_TOOLS
    for chunk in chunks:
        key = _evidence_key(chunk)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entry = dict(chunk)
        if mark_semantic:
            entry["from_semantic_search"] = True
        evidence.append(entry)


def parse_tool_filters(raw: dict | None, doc_ids: list[UUID] | None) -> ChunkFilter:
    if not raw:
        return ChunkFilter.from_request(doc_ids, None)
    try:
        filters = ChunkFilter.model_validate(raw)
    except ValidationError:
        return ChunkFilter.from_request(doc_ids, None)
    return ChunkFilter.from_request(doc_ids, filters if filters.has_constraints() else None)


def parse_batch_searches(action_input: dict, *, max_items: int) -> list[dict]:
    raw = action_input.get("searches")
    if not isinstance(raw, list):
        return []

    searches: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        searches.append(item)
        if len(searches) >= max_items:
            break
    return searches


def _parse_neighbor_count(raw: object, *, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, NEIGHBOR_READ_MAX))


def _parse_optional_positive_int(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 1 else None


def count_retrieval_units(action: str, action_input: dict, *, max_batch: int) -> int:
    if action == "search_chunks_batch":
        return len(parse_batch_searches(action_input, max_items=max_batch))
    if action in RETRIEVAL_TOOLS:
        return 1
    return 0


class AgentToolRegistry:
    def __init__(self, rag: RAGService) -> None:
        self.rag = rag

    async def _search_chunks(
        self,
        db: AsyncSession,
        *,
        query: str,
        question: str,
        doc_ids: list[UUID] | None,
        explicit_filters: ChunkFilter | None,
        search_input: dict,
        query_vector: list[float] | None = None,
    ) -> list[dict]:
        top_k = search_input.get("top_k")
        try:
            top_k = int(top_k) if top_k is not None else self.rag.settings.rag_top_k
        except (TypeError, ValueError):
            top_k = self.rag.settings.rag_top_k
        tool_filters = parse_tool_filters(search_input.get("filters"), doc_ids)
        chunk_filter = ChunkFilter.merge_sources(
            doc_ids,
            explicit_filters,
            tool_filters if tool_filters.has_constraints() else None,
        )
        return await self.rag.search_chunks(
            db,
            query or question,
            chunk_filter,
            top_k=top_k,
            query_vector=query_vector,
        )

    async def execute(
        self,
        db: AsyncSession,
        action: str,
        action_input: dict,
        *,
        question: str,
        doc_ids: list[UUID] | None,
        explicit_filters: ChunkFilter | None,
        retrieval_budget: int | None = None,
    ) -> tuple[str, list[dict], int]:
        """Return observation text, retrieved chunks, and retrieval units consumed.

        Only ``search_chunks`` / ``search_chunks_batch`` return non-zero units.
        """
        if action == "list_outline":
            documents = await _load_session_documents(db, doc_ids)
            return format_documents_outline(documents), outline_to_chunks(documents), 0

        if action == "list_documents":
            documents = await _load_session_documents(db, doc_ids, order_by_name=True)
            return format_documents_list(documents), [], 0

        if action == "lookup_toc":
            lookup_question = str(action_input.get("question") or question)
            chunks = await lookup_toc(
                db,
                lookup_question,
                doc_ids,
                top_k=self.rag.settings.rag_top_k,
            )
            return _format_chunks(chunks, source_tool="lookup_toc"), chunks, 0

        if action == "read_section":
            section = str(action_input.get("section") or "").strip() or None
            lookup_question = str(action_input.get("question") or question)
            if not section and not lookup_question.strip():
                return "read_section 需要 section 或 question。", [], 0
            document_id = _parse_optional_uuid(action_input.get("document_id"))
            chunks, resolved, error = await self.rag.read_section(
                db,
                lookup_question,
                doc_ids,
                section=section,
                document_id=document_id,
                max_chunks=PAGE_READ_MAX_CHUNKS,
            )
            if error:
                return error, [], 0
            observation = _format_chunks(
                chunks,
                source_tool="read_section",
                full_text=True,
            )
            if resolved is not None:
                observation += (
                    f"\n（章节 §{resolved.section_path} · "
                    f"p.{resolved.start_page}–{resolved.end_page} · 共 {len(chunks)} 条）"
                )
            return observation, chunks, 0

        if action == "search_chunks":
            query = str(action_input.get("query") or question).strip()
            chunks = await self._search_chunks(
                db,
                query=query,
                question=question,
                doc_ids=doc_ids,
                explicit_filters=explicit_filters,
                search_input=action_input,
            )
            return _format_chunks(chunks, source_tool="search_chunks"), chunks, 1

        if action == "search_keyword":
            if not self.rag.fulltext_store:
                return (
                    "search_keyword 需要启用全文检索（HYBRID_ENABLED=true）。",
                    [],
                    0,
                )
            query = str(action_input.get("query") or question).strip()
            if not query:
                return "search_keyword 需要 query。", [], 0
            tool_filters = parse_tool_filters(action_input.get("filters"), doc_ids)
            chunk_filter = ChunkFilter.merge_sources(
                doc_ids,
                explicit_filters,
                tool_filters if tool_filters.has_constraints() else None,
            )
            top_k = action_input.get("top_k")
            try:
                top_k = int(top_k) if top_k is not None else self.rag.settings.rag_top_k
            except (TypeError, ValueError):
                top_k = self.rag.settings.rag_top_k
            chunks = await self.rag.search_keyword(
                db,
                query,
                chunk_filter,
                top_k=top_k,
            )
            return _format_chunks(chunks, source_tool="search_keyword"), chunks, 1

        if action == "search_chunks_batch":
            max_batch = self.rag.settings.rag_batch_search_max
            searches = parse_batch_searches(action_input, max_items=max_batch)
            if retrieval_budget is not None:
                searches = searches[:retrieval_budget]
            if not searches:
                return "search_chunks_batch 需要非空 searches 列表。", [], 0

            queries = [str(item.get("query") or "").strip() for item in searches]
            query_vectors = await self.rag.embed_queries(queries)

            async def run_search(
                search_item: dict,
                query: str,
                query_vector: list[float],
            ) -> tuple[str, list[dict]]:
                async with async_session_factory() as search_db:
                    chunks = await self._search_chunks(
                        search_db,
                        query=query,
                        question=question,
                        doc_ids=doc_ids,
                        explicit_filters=explicit_filters,
                        search_input=search_item,
                        query_vector=query_vector,
                    )
                return query, chunks

            results = list(
                await asyncio.gather(
                    *[
                        run_search(search_item, query, query_vector)
                        for search_item, query, query_vector in zip(
                            searches, queries, query_vectors, strict=True
                        )
                    ]
                )
            )
            merged = _merge_batch_chunks(results)
            return _format_batch_observation(results), merged, len(searches)

        if action == "lookup_asset":
            figure_number = str(action_input.get("figure_number") or "").strip()
            if not figure_number:
                return "lookup_asset 需要 figure_number（如 4-7）。", [], 0
            kind = str(action_input.get("kind") or "").strip().lower() or None
            if kind not in {None, "figure", "table"}:
                kind = None
            document_id = _parse_optional_uuid(action_input.get("document_id"))
            chunks, error = await lookup_asset(
                db,
                figure_number,
                kind=kind,
                doc_ids=doc_ids,
                document_id=document_id,
                top_k=LOOKUP_ASSET_MAX,
            )
            if error:
                return error, [], 0
            observation = _format_chunks(chunks, source_tool="lookup_asset")
            return observation, chunks, 0

        if action == "read_pages":
            page = _parse_optional_positive_int(action_input.get("page"))
            page_gte = _parse_optional_positive_int(action_input.get("page_gte"))
            page_lte = _parse_optional_positive_int(action_input.get("page_lte"))
            document_id = _parse_optional_uuid(action_input.get("document_id"))
            chunks, error = await self.rag.read_pages(
                db,
                page=page,
                page_gte=page_gte,
                page_lte=page_lte,
                document_id=document_id,
                doc_ids=doc_ids,
                max_chunks=PAGE_READ_MAX_CHUNKS,
            )
            if error:
                return error, [], 0
            observation = _format_chunks(
                chunks,
                source_tool="read_pages",
                full_text=True,
            )
            if page is not None:
                observation += f"\n（页码 p.{page}，共 {len(chunks)} 条）"
            else:
                observation += (
                    f"\n（页码范围 p.{page_gte or '?'}"
                    f"–{page_lte or '?'}，共 {len(chunks)} 条）"
                )
            return observation, chunks, 0

        if action == "read_neighbor_chunks":
            anchor_id = str(action_input.get("chunk_id") or "").strip()
            if not anchor_id:
                return "read_neighbor_chunks 需要 chunk_id（锚点 UUID）。", [], 0
            before = _parse_neighbor_count(action_input.get("before"), default=1)
            after = _parse_neighbor_count(action_input.get("after"), default=1)
            chunks, error = await self.rag.read_neighbor_chunks(
                db,
                anchor_id,
                before=before,
                after=after,
            )
            if error:
                return error, [], 0
            observation = _format_chunks(
                chunks,
                source_tool="read_neighbor_chunks",
                full_text=True,
            )
            observation += f"\n（锚点 id={anchor_id}，前 {before} / 后 {after} 块，共 {len(chunks)} 条）"
            return observation, chunks, 0

        return f"未知工具：{action}", [], 0

    @staticmethod
    def cache_key(action: str, action_input: dict) -> str:
        return json.dumps({"action": action, "input": action_input}, sort_keys=True, ensure_ascii=False)
