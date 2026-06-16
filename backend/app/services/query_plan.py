import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.services.chunk_filter import ChunkFilter
from app.services.llm import LLMService, QueryIntent

logger = logging.getLogger(__name__)

QuerySlot = Literal["cause", "principle", "procedure"]

ALLOWED_CONTENT_ROLES = frozenset({"cause", "principle", "troubleshooting", "symptom"})
ALLOWED_CHUNK_TYPES = frozenset({"text", "procedure", "warning", "table"})


class SubQuery(BaseModel):
    slot: QuerySlot
    query: str
    content_roles: list[str] | None = None
    chunk_types: list[str] | None = None
    section_hints: list[str] | None = None


class QueryPlan(BaseModel):
    intent: QueryIntent = "general"
    symptom: str | None = None
    sub_queries: list[SubQuery] = Field(default_factory=list)
    top_k_per_slot: int = 3
    apply_metadata_filters: bool = False
    filters: ChunkFilter | None = None


def _default_troubleshooting_sub_queries(question: str, symptom: str | None) -> list[SubQuery]:
    focus = symptom or question
    return [
        SubQuery(
            slot="cause",
            query=f"{focus} 故障原因 可能原因",
            content_roles=["cause", "symptom"],
        ),
        SubQuery(
            slot="principle",
            query=f"{focus} 工作原理 原理 机制",
            content_roles=["principle"],
        ),
        SubQuery(
            slot="procedure",
            query=f"{focus} 排查 处理 解决 步骤",
            content_roles=["troubleshooting"],
            chunk_types=["procedure", "text"],
        ),
    ]


def _sanitize_string_list(
    values: object,
    allowed: frozenset[str],
) -> list[str] | None:
    if values is None:
        return None
    if not isinstance(values, list):
        return None
    cleaned = [value for value in values if isinstance(value, str) and value in allowed]
    return cleaned or None


def _sanitize_filters(payload: dict) -> ChunkFilter | None:
    chunk_types = _sanitize_string_list(payload.get("chunk_types"), ALLOWED_CHUNK_TYPES)
    content_roles = _sanitize_string_list(payload.get("content_roles"), ALLOWED_CONTENT_ROLES)

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
            content_roles=content_roles,
            page_gte=page_gte,
            page_lte=page_lte,
            section_prefix=section_prefix,
            section_contains=section_contains,
        )
    except ValidationError:
        return None
    return result if result.has_constraints() else None


def _sanitize_sub_query(raw: dict) -> SubQuery | None:
    slot = raw.get("slot")
    query = raw.get("query")
    if slot not in {"cause", "principle", "procedure"}:
        return None
    if not isinstance(query, str) or not query.strip():
        return None
    return SubQuery(
        slot=slot,
        query=query.strip(),
        content_roles=_sanitize_string_list(raw.get("content_roles"), ALLOWED_CONTENT_ROLES),
        chunk_types=_sanitize_string_list(raw.get("chunk_types"), ALLOWED_CHUNK_TYPES),
        section_hints=[
            hint.strip()
            for hint in raw.get("section_hints", []) or []
            if isinstance(hint, str) and hint.strip()
        ]
        or None,
    )


def sanitize_query_plan(payload: dict, question: str) -> QueryPlan:
    intent = payload.get("intent")
    if intent not in {"troubleshooting", "how_to", "spec", "general"}:
        intent = "general"

    symptom = payload.get("symptom")
    if not isinstance(symptom, str) or not symptom.strip():
        symptom = None
    else:
        symptom = symptom.strip()

    top_k_per_slot = payload.get("top_k_per_slot", 3)
    try:
        top_k_per_slot = max(1, min(int(top_k_per_slot), 6))
    except (TypeError, ValueError):
        top_k_per_slot = 3

    apply_metadata_filters = bool(payload.get("apply_metadata_filters"))

    filters_raw = payload.get("filters")
    filters = _sanitize_filters(filters_raw) if isinstance(filters_raw, dict) else None

    sub_queries: list[SubQuery] = []
    for raw in payload.get("sub_queries") or []:
        if isinstance(raw, dict):
            sub_query = _sanitize_sub_query(raw)
            if sub_query:
                sub_queries.append(sub_query)

    if intent == "troubleshooting":
        if len(sub_queries) < 3:
            existing_slots = {item.slot for item in sub_queries}
            for default in _default_troubleshooting_sub_queries(question, symptom):
                if default.slot not in existing_slots:
                    sub_queries.append(default)
        sub_queries.sort(key=lambda item: {"cause": 0, "principle": 1, "procedure": 2}[item.slot])
        apply_metadata_filters = False

    return QueryPlan(
        intent=intent,
        symptom=symptom,
        sub_queries=sub_queries,
        top_k_per_slot=top_k_per_slot,
        apply_metadata_filters=apply_metadata_filters,
        filters=filters,
    )


class QueryPlannerService:
    def __init__(self, settings: Settings | None = None, llm: LLMService | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or LLMService(self.settings)

    async def plan(self, question: str) -> QueryPlan:
        if not self.settings.rag_query_planner_enabled:
            return QueryPlan(intent="general")

        try:
            payload = await self.llm.plan_query(question)
        except Exception:
            logger.warning("Query planner LLM call failed", exc_info=True)
            payload = {}

        plan = sanitize_query_plan(payload if isinstance(payload, dict) else {}, question)
        logger.info(
            "Query plan: intent=%s symptom=%s sub_queries=%d filters=%s",
            plan.intent,
            plan.symptom,
            len(plan.sub_queries),
            plan.filters.model_dump(exclude_none=True) if plan.filters else None,
        )
        return plan
