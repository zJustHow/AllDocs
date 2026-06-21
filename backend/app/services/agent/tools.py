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
READ_FULL_TEXT_TOKEN_BUDGET = 6000
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


def _estimate_text_tokens(text: str) -> int:
    """Conservative tokenizer-free estimate for mixed Chinese/Latin manual text."""
    if not text:
        return 0
    cjk = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    return cjk + max(1, (len(text) - cjk + 3) // 4)


def _limit_full_text_chunks(
    chunks: list[dict],
    *,
    token_budget: int = READ_FULL_TEXT_TOKEN_BUDGET,
) -> tuple[list[dict], bool]:
    """Keep complete chunks within budget, always preserving at least one chunk."""
    limited: list[dict] = []
    used = 0
    for chunk in chunks:
        cost = _estimate_text_tokens(_format_chunk_body(chunk, full_text=True)) + 80
        if limited and used + cost > token_budget:
            return limited, True
        limited.append(chunk)
        used += cost
    return limited, False


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


def _parse_optional_uuid(raw: object, *, field: str = "document_id") -> UUID | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return UUID(text)
    except ValueError as exc:
        raise ValueError(f"{field} 必须是有效 UUID。") from exc


def _validate_document_scope(
    document_id: UUID | None, doc_ids: list[UUID] | None
) -> None:
    if document_id is not None and doc_ids and document_id not in doc_ids:
        raise ValueError("document_id 不在当前会话文档范围内。")


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
    except ValidationError as exc:
        raise ValueError(f"filters 参数无效：{exc.errors()[0]['msg']}") from exc
    if filters.asset_types and any(
        asset_type not in {"table", "figure"} for asset_type in filters.asset_types
    ):
        raise ValueError("filters.asset_types 仅支持 table 或 figure。")
    if (
        filters.page_gte is not None
        and filters.page_lte is not None
        and filters.page_gte > filters.page_lte
    ):
        raise ValueError("filters.page_gte 不能大于 page_lte。")
    scoped = ChunkFilter.from_request(
        doc_ids, filters if filters.has_constraints() else None
    )
    if filters.document_ids and doc_ids and not scoped.document_ids:
        raise ValueError("filters.document_ids 不在当前会话文档范围内。")
    return scoped


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


def _parse_optional_positive_int(raw: object, *, field: str) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是正整数。") from exc
    if value < 1:
        raise ValueError(f"{field} 必须是正整数。")
    return value


def _parse_non_negative_int(raw: object, *, field: str, default: int = 0) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是非负整数。") from exc
    if value < 0:
        raise ValueError(f"{field} 必须是非负整数。")
    return value


def _parse_top_k(raw: object, *, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("top_k 必须是 1–20 的整数。") from exc
    if not 1 <= value <= 20:
        raise ValueError("top_k 必须是 1–20 的整数。")
    return value


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
        top_k = _parse_top_k(
            search_input.get("top_k"), default=self.rag.settings.rag_top_k
        )
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
            try:
                offset = _parse_non_negative_int(action_input.get("offset"), field="offset")
                document_id = _parse_optional_uuid(action_input.get("document_id"))
                _validate_document_scope(document_id, doc_ids)
            except ValueError as exc:
                return str(exc), [], 0
            if not section and not lookup_question.strip():
                return "read_section 需要 section 或 question。", [], 0
            chunks, resolved, page, error = await self.rag.read_section(
                db,
                lookup_question,
                doc_ids,
                section=section,
                document_id=document_id,
                max_chunks=PAGE_READ_MAX_CHUNKS,
                offset=offset,
            )
            if error:
                return error, [], 0
            chunks, token_limited = _limit_full_text_chunks(chunks)
            observation = _format_chunks(
                chunks,
                source_tool="read_section",
                full_text=True,
            )
            if resolved is not None:
                observation += (
                    f"\n（章节 §{resolved.section_path} · "
                    f"p.{resolved.start_page}–{resolved.end_page} · "
                    f"本页 {len(chunks)} 条 · offset={offset}）"
                )
            has_more = token_limited or (page is not None and page.has_more)
            if has_more:
                next_offset = (
                    offset + len(chunks)
                    if token_limited
                    else page.next_offset if page is not None else offset + len(chunks)
                )
                observation += (
                    "\n⚠️ 本章内容已截断，仍有后续 chunk。"
                    f"请继续调用 read_section，并保持相同章节参数、设置 "
                    f"offset={next_offset}。"
                )
            elif page is not None and offset > 0:
                observation += "\n（本章已读取完毕，无更多 chunk。）"
            return observation, chunks, 0

        if action == "search_chunks":
            query = str(action_input.get("query") or question).strip()
            try:
                chunks = await self._search_chunks(
                    db,
                    query=query,
                    question=question,
                    doc_ids=doc_ids,
                    explicit_filters=explicit_filters,
                    search_input=action_input,
                )
            except ValueError as exc:
                return str(exc), [], 0
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
            try:
                tool_filters = parse_tool_filters(action_input.get("filters"), doc_ids)
            except ValueError as exc:
                return str(exc), [], 0
            chunk_filter = ChunkFilter.merge_sources(
                doc_ids,
                explicit_filters,
                tool_filters if tool_filters.has_constraints() else None,
            )
            try:
                top_k = _parse_top_k(
                    action_input.get("top_k"), default=self.rag.settings.rag_top_k
                )
            except ValueError as exc:
                return str(exc), [], 0
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
            try:
                for item in searches:
                    parse_tool_filters(item.get("filters"), doc_ids)
                    _parse_top_k(item.get("top_k"), default=self.rag.settings.rag_top_k)
            except ValueError as exc:
                return str(exc), [], 0
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
                return "kind 仅支持 figure 或 table。", [], 0
            try:
                document_id = _parse_optional_uuid(action_input.get("document_id"))
                _validate_document_scope(document_id, doc_ids)
            except ValueError as exc:
                return str(exc), [], 0
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
            try:
                page = _parse_optional_positive_int(action_input.get("page"), field="page")
                page_gte = _parse_optional_positive_int(
                    action_input.get("page_gte"), field="page_gte"
                )
                page_lte = _parse_optional_positive_int(
                    action_input.get("page_lte"), field="page_lte"
                )
                offset = _parse_non_negative_int(action_input.get("offset"), field="offset")
                document_id = _parse_optional_uuid(action_input.get("document_id"))
                _validate_document_scope(document_id, doc_ids)
                if page is not None and (page_gte is not None or page_lte is not None):
                    raise ValueError("page 与 page_gte/page_lte 不能同时使用。")
                if page_gte is not None and page_lte is not None and page_gte > page_lte:
                    raise ValueError("page_gte 不能大于 page_lte。")
            except ValueError as exc:
                return str(exc), [], 0
            chunks, error = await self.rag.read_pages(
                db,
                page=page,
                page_gte=page_gte,
                page_lte=page_lte,
                document_id=document_id,
                doc_ids=doc_ids,
                max_chunks=PAGE_READ_MAX_CHUNKS + 1,
                offset=offset,
            )
            if error:
                return error, [], 0
            db_has_more = len(chunks) > PAGE_READ_MAX_CHUNKS
            chunks = chunks[:PAGE_READ_MAX_CHUNKS]
            chunks, token_limited = _limit_full_text_chunks(chunks)
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
            if db_has_more or token_limited:
                observation += (
                    "\n⚠️ 页面内容已截断，仍有后续 chunk。请保持相同页码参数，"
                    f"继续调用 read_pages，并设置 offset={offset + len(chunks)}。"
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

        if action == "finish":
            reason = str(action_input.get("reason") or "进入回答阶段").strip()
            key_evidence_ids = parse_finish_key_evidence_ids(action_input)
            observation = reason
            if key_evidence_ids:
                observation += f"\n关键证据：{', '.join(key_evidence_ids)}"
            return observation, [], 0

        return f"未知工具：{action}", [], 0

    @staticmethod
    def cache_key(action: str, action_input: dict) -> str:
        return json.dumps({"action": action, "input": action_input}, sort_keys=True, ensure_ascii=False)
