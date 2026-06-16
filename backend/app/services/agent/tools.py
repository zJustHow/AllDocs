import asyncio
import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.services.chunk_filter import ChunkFilter
from app.services.ingestion import toc_entries_from_dicts
from app.services.rag import RAGService
from app.services.toc_lookup import lookup_toc

RETRIEVAL_TOOLS = frozenset(
    {"list_outline", "lookup_toc", "search_chunks", "search_chunks_batch", "read_chunks"}
)
SEMANTIC_SEARCH_ACTIONS = frozenset({"search_chunks", "search_chunks_batch"})


def _evidence_key(chunk: dict) -> str:
    chunk_id = chunk.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    return (
        f"{chunk.get('document_id')}:{chunk.get('page')}:"
        f"{chunk.get('section') or ''}"
    )


def _format_outline(documents: list[Document]) -> str:
    if not documents:
        return "未找到可用文档目录（可能 PDF 无书签，需重新处理文档）。"

    parts: list[str] = []
    for document in documents:
        if not document.toc_entries:
            parts.append(f"《{document.name}》：无书签目录")
            continue
        entries = toc_entries_from_dicts(document.toc_entries)
        lines = [f"《{document.name}》章节树："]
        for entry in entries[:80]:
            indent = "  " * max(entry.level - 1, 0)
            lines.append(
                f"{indent}- {entry.title} (p.{entry.start_page}-p.{entry.end_page})"
            )
        if len(entries) > 80:
            lines.append(f"  ... 共 {len(entries)} 条，已截断")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _format_chunks(chunks: list[dict], *, source_tool: str) -> str:
    if not chunks:
        return "未检索到相关内容。"

    lines = [f"检索工具：{source_tool}，命中 {len(chunks)} 条："]
    for index, item in enumerate(chunks, start=1):
        header = f"[{index}] {item.get('document_name', '')}"
        if item.get("page"):
            header += f" p.{item['page']}"
        if item.get("section"):
            header += f" §{item.get('section')}"
        if item.get("content_role"):
            header += f" role={item['content_role']}"
        snippet = (item.get("snippet") or item.get("text") or "")[:240]
        lines.append(f"{header}\n{snippet}")
    return "\n\n".join(lines)


def _format_batch_observation(results: list[tuple[str, list[dict]]]) -> str:
    if not results:
        return "search_chunks_batch 需要非空 searches 列表。"

    total = sum(len(chunks) for _, chunks in results)
    lines = [f"并行检索 {len(results)} 路，合计命中 {total} 条："]
    for index, (query, chunks) in enumerate(results, start=1):
        lines.append(f"\n--- 检索 {index}：{query} · 命中 {len(chunks)} 条 ---")
        if not chunks:
            lines.append("（无结果）")
            continue
        for hit, item in enumerate(chunks, start=1):
            header = f"  [{hit}] {item.get('document_name', '')}"
            if item.get("page"):
                header += f" p.{item['page']}"
            if item.get("content_role"):
                header += f" role={item['content_role']}"
            snippet = (item.get("snippet") or item.get("text") or "")[:160]
            lines.append(f"{header}\n    {snippet}")
    return "\n".join(lines)


def merge_chunks_into_evidence(
    evidence: list[dict],
    seen_keys: set[str],
    chunks: list[dict],
    *,
    source_action: str | None = None,
) -> None:
    mark_semantic = source_action in SEMANTIC_SEARCH_ACTIONS
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


def parse_batch_searches(action_input: dict, question: str, *, max_items: int) -> list[dict]:
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


def count_retrieval_units(action: str, action_input: dict, *, max_batch: int) -> int:
    if action == "search_chunks_batch":
        return len(parse_batch_searches(action_input, "", max_items=max_batch))
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
        """Return observation text, retrieved chunks, and retrieval units consumed."""
        if action == "finish":
            reason = str(action_input.get("reason") or "证据已足够")
            return f"结束检索：{reason}", [], 0

        if action == "list_outline":
            stmt = select(Document)
            if doc_ids:
                stmt = stmt.where(Document.id.in_(doc_ids))
            result = await db.execute(stmt)
            documents = list(result.scalars().all())
            return _format_outline(documents), [], 1

        if action == "lookup_toc":
            lookup_question = str(action_input.get("question") or question)
            chunks = await lookup_toc(
                db,
                lookup_question,
                doc_ids,
                top_k=self.rag.settings.rag_top_k,
            )
            return _format_chunks(chunks, source_tool="lookup_toc"), chunks, 1

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

        if action == "search_chunks_batch":
            max_batch = self.rag.settings.rag_batch_search_max
            searches = parse_batch_searches(action_input, question, max_items=max_batch)
            if retrieval_budget is not None:
                searches = searches[:retrieval_budget]
            if not searches:
                return "search_chunks_batch 需要非空 searches 列表。", [], 0

            async def run_one(search_item: dict) -> tuple[str, list[dict]]:
                query = str(search_item.get("query") or question).strip()
                chunks = await self._search_chunks(
                    db,
                    query=query,
                    question=question,
                    doc_ids=doc_ids,
                    explicit_filters=explicit_filters,
                    search_input=search_item,
                )
                return query, chunks

            results = await asyncio.gather(*(run_one(item) for item in searches))
            merged: list[dict] = []
            for _, chunks in results:
                merged.extend(chunks)
            return _format_batch_observation(results), merged, len(searches)

        if action == "read_chunks":
            raw_ids = action_input.get("chunk_ids") or []
            if not isinstance(raw_ids, list) or not raw_ids:
                return "read_chunks 需要非空 chunk_ids 列表。", [], 1
            chunk_ids = [str(item) for item in raw_ids][:10]
            chunks = await self.rag.read_chunks(db, chunk_ids)
            return _format_chunks(chunks, source_tool="read_chunks"), chunks, 1

        return f"未知工具：{action}", [], 0

    @staticmethod
    def cache_key(action: str, action_input: dict) -> str:
        return json.dumps({"action": action, "input": action_input}, sort_keys=True, ensure_ascii=False)
