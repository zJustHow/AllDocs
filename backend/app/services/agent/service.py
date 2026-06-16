import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.services.agent.state import AgentResult, AgentState, AgentStep, OnAgentStep
from app.services.agent.tools import RETRIEVAL_TOOLS, AgentToolRegistry, merge_citations_into_evidence
from app.services.chunk_filter import ChunkFilter
from app.services.citations_util import evidence_to_citations, finalize_answer_citations
from app.services.llm import LLMService, QueryIntent
from app.services.query_plan import QueryPlannerService
from app.services.rag import RAGService, detect_language, not_found_message

logger = logging.getLogger(__name__)


class AgentRAGService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.rag = RAGService(self.settings)
        self.llm = LLMService(self.settings)
        self.planner = QueryPlannerService(self.settings, self.llm)
        self.tools = AgentToolRegistry(self.rag)

    async def _planner_hint(self, question: str) -> dict:
        if not self.settings.rag_agent_planner_hint or not self.settings.rag_query_planner_enabled:
            return {}
        try:
            plan = await self.planner.plan(question)
        except Exception:
            logger.warning("Agent planner hint failed", exc_info=True)
            return {}
        hint = {
            "intent": plan.intent,
            "symptom": plan.symptom,
            "apply_metadata_filters": plan.apply_metadata_filters,
        }
        if plan.filters:
            hint["filters"] = plan.filters.model_dump(exclude_none=True)
        if plan.sub_queries:
            hint["sub_queries"] = [
                {
                    "slot": item.slot,
                    "query": item.query,
                    "content_roles": item.content_roles,
                    "chunk_types": item.chunk_types,
                }
                for item in plan.sub_queries
            ]
        return hint

    async def _emit_step(self, callback: OnAgentStep | None, payload: dict) -> None:
        if callback is None:
            return
        result = callback(payload)
        if result is not None:
            await result

    async def iter_synthesis(
        self,
        question: str,
        evidence: list[dict],
        chat_history: list[dict[str, str]] | None,
        intent: QueryIntent = "general",
    ) -> AsyncIterator[str]:
        citations = evidence_to_citations(evidence)
        context = self.rag.build_context(citations)
        async for delta in self.llm.chat_stream(question, context, chat_history, intent=intent):
            yield delta

    async def run(
        self,
        db: AsyncSession,
        question: str,
        doc_ids: list[UUID] | None = None,
        filters: ChunkFilter | None = None,
        chat_history: list[dict[str, str]] | None = None,
        *,
        on_step: OnAgentStep | None = None,
        skip_synthesis: bool = False,
    ) -> AgentResult:
        lang = detect_language(question)
        state = AgentState()
        planner_hint = await self._planner_hint(question)
        if planner_hint.get("intent") in {"troubleshooting", "how_to", "spec", "general"}:
            state.intent = planner_hint["intent"]

        if planner_hint:
            await self._emit_step(
                on_step,
                {
                    "type": "agent_planner_hint",
                    "hint": planner_hint,
                },
            )

        while len(state.steps) < self.settings.rag_agent_max_steps and not state.done:
            action_payload = await self.llm.decide_agent_action(
                question,
                state.steps,
                planner_hint if not state.steps else None,
            )
            thought = str(action_payload.get("thought") or "")
            action = str(action_payload.get("action") or "finish").strip()
            action_input = action_payload.get("action_input")
            if not isinstance(action_input, dict):
                action_input = {}

            if action == "finish":
                state.done = True
                step = AgentStep(
                    step=len(state.steps) + 1,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation="进入回答阶段。",
                )
                state.steps.append(step)
                await self._emit_step(
                    on_step,
                    {
                        "type": "agent_step",
                        "step": step.step,
                        "thought": step.thought,
                        "action": step.action,
                        "action_input": step.action_input,
                        "observation": step.observation,
                    },
                )
                break

            cache_key = self.tools.cache_key(action, action_input)
            if cache_key in state.tool_cache:
                observation = state.tool_cache[cache_key]
                citations: list[dict] = []
                intent_override = None
            else:
                if action in RETRIEVAL_TOOLS:
                    if state.retrieval_calls >= self.settings.rag_agent_max_retrievals:
                        observation = "检索次数已达上限，请调用 finish。"
                        citations = []
                        intent_override = None
                    else:
                        state.retrieval_calls += 1
                        observation, citations, intent_override = await self.tools.execute(
                            db,
                            action,
                            action_input,
                            question=question,
                            doc_ids=doc_ids,
                            explicit_filters=filters,
                        )
                        if intent_override:
                            state.intent = intent_override
                else:
                    observation, citations, intent_override = await self.tools.execute(
                        db,
                        action,
                        action_input,
                        question=question,
                        doc_ids=doc_ids,
                        explicit_filters=filters,
                    )
                state.tool_cache[cache_key] = observation

            merge_citations_into_evidence(
                state.evidence,
                state.seen_evidence_keys,
                citations,
                source_tool=action,
            )

            step = AgentStep(
                step=len(state.steps) + 1,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
            )
            state.steps.append(step)
            await self._emit_step(
                on_step,
                {
                    "type": "agent_step",
                    "step": step.step,
                    "thought": step.thought,
                    "action": step.action,
                    "action_input": step.action_input,
                    "observation": step.observation,
                    "evidence_count": len(state.evidence),
                },
            )

        if not state.done:
            state.done = True
            logger.info("Agent reached max steps (%d); forcing synthesis", self.settings.rag_agent_max_steps)

        citations_for_context = evidence_to_citations(state.evidence)

        if not citations_for_context:
            fallback = not_found_message(lang)
            return AgentResult(
                answer=fallback,
                citations=[],
                intent=state.intent,
                language=lang,
                steps=state.steps,
                evidence=state.evidence,
            )

        if skip_synthesis:
            return AgentResult(
                answer="",
                citations=[],
                intent=state.intent,
                language=lang,
                steps=state.steps,
                evidence=state.evidence,
            )

        context = self.rag.build_context(citations_for_context)
        answer = await self.llm.chat(question, context, chat_history, intent=state.intent)
        answer, public_citations = finalize_answer_citations(answer, citations_for_context)

        trace = [
            {
                "step": step.step,
                "thought": step.thought,
                "action": step.action,
                "action_input": step.action_input,
            }
            for step in state.steps
        ]
        logger.info("Agent completed: steps=%d evidence=%d trace=%s", len(state.steps), len(state.evidence), json.dumps(trace, ensure_ascii=False))

        return AgentResult(
            answer=answer,
            citations=public_citations,
            intent=state.intent,
            language=lang,
            steps=state.steps,
            evidence=state.evidence,
        )
