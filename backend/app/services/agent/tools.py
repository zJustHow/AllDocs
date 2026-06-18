import asyncio
import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.db.session import async_session_factory
from app.services.chunk_filter import ChunkFilter, chunk_asset_types
from app.services.rag import RAGService, parse_chunk_uuids
from app.services.toc_lookup import format_documents_outline, lookup_toc, outline_to_chunks

RETRIEVAL_TOOLS = frozenset({"search_chunks", "search_chunks_batch"})
SEMANTIC_SEARCH_ACTIONS = frozenset({"search_chunks", "search_chunks_batch"})
NEIGHBOR_READ_MAX = 3


def _evidence_key(chunk: dict) -> str:
    chunk_id = chunk.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    return (
        f"{chunk.get('document_id')}:{chunk.get('page')}:"
        f"{chunk.get('section') or ''}"
    )


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
        asset_types = chunk_asset_types(item)
        if asset_types:
            header += f" assets={','.join(asset_types)}"
        if item.get("assets"):
            header += " visual=1"
        if item.get("caption") or any(
            asset.get("caption") or asset.get("figure_caption")
            for asset in item.get("assets") or []
        ):
            header += " caption=1"
        chunk_id = item.get("chunk_id")
        if chunk_id:
            header += f" id={chunk_id}"
        chunk_index = item.get("chunk_index")
        if chunk_index is not None:
            header += f" idx={chunk_index}"
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
            asset_types = chunk_asset_types(item)
            if asset_types:
                header += f" assets={','.join(asset_types)}"
            chunk_id = item.get("chunk_id")
            if chunk_id:
                header += f" id={chunk_id}"
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


def _parse_neighbor_count(raw: object, *, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return max(0, min(value, NEIGHBOR_READ_MAX))


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
            return format_documents_outline(documents), outline_to_chunks(documents), 1

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

            queries = [str(item.get("query") or question).strip() for item in searches]
            query_vectors = await self.rag._embed_queries(queries)

            async def run_one(
                search_item: dict, query_vector: list[float]
            ) -> tuple[str, list[dict]]:
                query = str(search_item.get("query") or question).strip()
                async with async_session_factory() as task_db:
                    chunks = await self._search_chunks(
                        task_db,
                        query=query,
                        question=question,
                        doc_ids=doc_ids,
                        explicit_filters=explicit_filters,
                        search_input=search_item,
                        query_vector=query_vector,
                    )
                return query, chunks

            results = await asyncio.gather(
                *(
                    run_one(item, query_vector)
                    for item, query_vector in zip(searches, query_vectors, strict=True)
                )
            )
            merged: list[dict] = []
            for _, chunks in results:
                merged.extend(chunks)
            return _format_batch_observation(results), merged, len(searches)

        if action == "read_chunks":
            raw_ids = action_input.get("chunk_ids") or []
            if not isinstance(raw_ids, list) or not raw_ids:
                return "read_chunks 需要非空 chunk_ids 列表。", [], 1
            chunk_ids = [str(item) for item in raw_ids][:10]
            valid_ids, invalid_ids = parse_chunk_uuids(chunk_ids)
            if not valid_ids:
                hint = "read_chunks 需要有效的 chunk_id（UUID），请使用上一步检索结果中的 id= 字段，不要用 [1][2] 序号。"
                if invalid_ids:
                    hint += f" 无效值：{', '.join(invalid_ids[:5])}"
                return hint, [], 1
            chunks = await self.rag.read_chunks(db, [str(chunk_id) for chunk_id in valid_ids])
            observation = _format_chunks(chunks, source_tool="read_chunks")
            if invalid_ids:
                observation += f"\n（已忽略无效 chunk_id：{', '.join(invalid_ids[:5])}）"
            return observation, chunks, 1

        if action == "read_neighbor_chunks":
            anchor_id = str(action_input.get("chunk_id") or "").strip()
            if not anchor_id:
                return "read_neighbor_chunks 需要 chunk_id（锚点 UUID）。", [], 1
            before = _parse_neighbor_count(action_input.get("before"), default=1)
            after = _parse_neighbor_count(action_input.get("after"), default=1)
            chunks, error = await self.rag.read_neighbor_chunks(
                db,
                anchor_id,
                before=before,
                after=after,
            )
            if error:
                return error, [], 1
            observation = _format_chunks(chunks, source_tool="read_neighbor_chunks")
            observation += f"\n（锚点 id={anchor_id}，前 {before} / 后 {after} 块，共 {len(chunks)} 条）"
            return observation, chunks, 1

        return f"未知工具：{action}", [], 0

    @staticmethod
    def cache_key(action: str, action_input: dict) -> str:
        return json.dumps({"action": action, "input": action_input}, sort_keys=True, ensure_ascii=False)
