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
    {"list_outline", "lookup_toc", "search_chunks", "search_troubleshooting", "read_chunks"}
)


def _evidence_key(citation: dict) -> str:
    chunk_id = citation.get("chunk_id")
    if chunk_id:
        return str(chunk_id)
    return (
        f"{citation.get('document_id')}:{citation.get('page')}:"
        f"{citation.get('section') or ''}"
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


def _format_citations(citations: list[dict], *, source_tool: str) -> str:
    if not citations:
        return "未检索到相关内容。"

    lines = [f"检索工具：{source_tool}，命中 {len(citations)} 条："]
    for index, item in enumerate(citations, start=1):
        header = f"[{index}] {item.get('document_name', '')}"
        if item.get("page"):
            header += f" p.{item['page']}"
        if item.get("section"):
            header += f" §{item.get('section')}"
        if item.get("slot"):
            header += f" slot={item['slot']}"
        snippet = (item.get("snippet") or item.get("text") or "")[:240]
        lines.append(f"{header}\n{snippet}")
    return "\n\n".join(lines)


def merge_citations_into_evidence(
    evidence: list[dict],
    seen_keys: set[str],
    citations: list[dict],
    *,
    source_tool: str,
) -> None:
    for citation in citations:
        key = _evidence_key(citation)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        evidence.append(
            {
                **citation,
                "evidence_id": len(evidence) + 1,
                "source_tool": source_tool,
            }
        )


def parse_tool_filters(raw: dict | None, doc_ids: list[UUID] | None) -> ChunkFilter:
    if not raw:
        return ChunkFilter.from_request(doc_ids, None)
    try:
        filters = ChunkFilter.model_validate(raw)
    except ValidationError:
        return ChunkFilter.from_request(doc_ids, None)
    return ChunkFilter.from_request(doc_ids, filters if filters.has_constraints() else None)


class AgentToolRegistry:
    def __init__(self, rag: RAGService) -> None:
        self.rag = rag

    async def execute(
        self,
        db: AsyncSession,
        action: str,
        action_input: dict,
        *,
        question: str,
        doc_ids: list[UUID] | None,
        explicit_filters: ChunkFilter | None,
    ) -> tuple[str, list[dict], str | None]:
        """Return observation text, new citations, and optional intent override."""
        if action == "finish":
            reason = str(action_input.get("reason") or "证据已足够")
            return f"结束检索：{reason}", [], None

        if action == "list_outline":
            stmt = select(Document)
            if doc_ids:
                stmt = stmt.where(Document.id.in_(doc_ids))
            result = await db.execute(stmt)
            documents = list(result.scalars().all())
            return _format_outline(documents), [], None

        if action == "lookup_toc":
            lookup_question = str(action_input.get("question") or question)
            citations = await lookup_toc(
                db,
                lookup_question,
                doc_ids,
                top_k=self.rag.settings.rag_top_k,
            )
            return _format_citations(citations, source_tool="lookup_toc"), citations, None

        if action == "search_chunks":
            query = str(action_input.get("query") or question).strip()
            top_k = action_input.get("top_k")
            try:
                top_k = int(top_k) if top_k is not None else self.rag.settings.rag_top_k
            except (TypeError, ValueError):
                top_k = self.rag.settings.rag_top_k
            tool_filters = parse_tool_filters(action_input.get("filters"), doc_ids)
            chunk_filter = ChunkFilter.merge_sources(
                doc_ids,
                explicit_filters,
                tool_filters if tool_filters.has_constraints() else None,
            )
            citations = await self.rag.search_chunks(
                db,
                query,
                chunk_filter,
                top_k=top_k,
            )
            return (
                _format_citations(citations, source_tool="search_chunks"),
                citations,
                None,
            )

        if action == "search_troubleshooting":
            troubleshoot_question = str(action_input.get("question") or question).strip()
            base_filter = ChunkFilter.from_request(doc_ids, explicit_filters)
            citations, intent = await self.rag.search_troubleshooting(
                db,
                troubleshoot_question,
                base_filter,
            )
            return (
                _format_citations(citations, source_tool="search_troubleshooting"),
                citations,
                intent,
            )

        if action == "read_chunks":
            raw_ids = action_input.get("chunk_ids") or []
            if not isinstance(raw_ids, list) or not raw_ids:
                return "read_chunks 需要非空 chunk_ids 列表。", [], None
            chunk_ids = [str(item) for item in raw_ids][:10]
            citations = await self.rag.read_chunks(db, chunk_ids)
            return _format_citations(citations, source_tool="read_chunks"), citations, None

        return f"未知工具：{action}", [], None

    @staticmethod
    def cache_key(action: str, action_input: dict) -> str:
        return json.dumps({"action": action, "input": action_input}, sort_keys=True, ensure_ascii=False)
