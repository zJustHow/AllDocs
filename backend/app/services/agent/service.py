import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.services.agent.state import AgentResult, AgentState, AgentStep, OnAgentStep
from app.services.agent.tools import (
    RETRIEVAL_TOOLS,
    SEMANTIC_SEARCH_ACTIONS,
    AgentToolRegistry,
    count_retrieval_units,
    merge_chunks_into_evidence,
)
from app.services.chunk_filter import ChunkFilter
from app.services.citations_util import finalize_answer
from app.services.llm import LLMService
from app.services.embeds_util import evidence_has_visual
from app.services.vision_util import VisionImage, prepare_vision_images

from app.services.rag import RAGService, detect_language, resolve_retrieval_fallback

logger = logging.getLogger(__name__)


class AgentRAGService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.rag = RAGService(self.settings)
        self.llm = LLMService(self.settings)
        self.tools = AgentToolRegistry(self.rag)

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
        vision_images: list[VisionImage] | None = None,
        *,
        lang: str | None = None,
    ) -> AsyncIterator[str]:
        context = self.rag.build_context(evidence)
        response_lang = lang or detect_language(question)
        use_vision = (
            self.settings.llm_vision_enabled
            and vision_images
        )
        include_embed_rules = not use_vision and evidence_has_visual(evidence)
        stream = (
            self.llm.chat_stream_vision(
                question, context, vision_images, chat_history, lang=response_lang
            )
            if use_vision
            else self.llm.chat_stream(
                question,
                context,
                chat_history,
                include_embed_rules=include_embed_rules,
                lang=response_lang,
            )
        )
        async for delta in stream:
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

        while len(state.steps) < self.settings.rag_agent_max_steps and not state.done:
            step_num = len(state.steps) + 1
            await self._emit_step(
                on_step,
                {
                    "type": "agent_step_start",
                    "step": step_num,
                    "thought": "",
                    "action": "planning",
                    "action_input": {},
                },
            )

            action_payload: dict | None = None
            async for stream_event in self.llm.decide_agent_action_stream(
                question, state.steps
            ):
                if stream_event["type"] == "delta":
                    await self._emit_step(
                        on_step,
                        {
                            "type": "agent_thought_delta",
                            "step": step_num,
                            "delta": stream_event["delta"],
                            "field": stream_event["field"],
                        },
                    )
                    continue
                if stream_event["type"] == "result":
                    action_payload = stream_event["payload"]

            if action_payload is None:
                action_payload = {
                    "thought": "fallback",
                    "reasoning_content": "",
                    "action": "finish",
                    "action_input": {"reason": "no agent response"},
                }

            thought = str(action_payload.get("thought") or "")
            reasoning_content = str(action_payload.get("reasoning_content") or "")
            action = str(action_payload.get("action") or "finish").strip()
            action_input = action_payload.get("action_input")
            if not isinstance(action_input, dict):
                action_input = {}

            await self._emit_step(
                on_step,
                {
                    "type": "agent_step_start",
                    "step": step_num,
                    "thought": thought,
                    "reasoning": reasoning_content,
                    "action": action,
                    "action_input": action_input,
                },
            )

            if action == "finish":
                state.done = True
                step = AgentStep(
                    step=step_num,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation="进入回答阶段。",
                    reasoning_content=reasoning_content,
                )
                state.steps.append(step)
                await self._emit_step(
                    on_step,
                    {
                        "type": "agent_step",
                        "step": step.step,
                        "thought": step.thought,
                        "reasoning": step.reasoning_content,
                        "action": step.action,
                        "action_input": step.action_input,
                        "observation": step.observation,
                    },
                )
                break

            cache_key = self.tools.cache_key(action, action_input)
            retrieval_units = 0
            if cache_key in state.tool_cache:
                observation = state.tool_cache[cache_key]
                chunks: list[dict] = []
            else:
                if action in RETRIEVAL_TOOLS:
                    max_batch = self.settings.rag_batch_search_max
                    planned_units = count_retrieval_units(
                        action,
                        action_input,
                        max_batch=max_batch,
                    )
                    remaining = self.settings.rag_agent_max_retrievals - state.retrieval_calls
                    if remaining <= 0:
                        observation = (
                            "检索次数已达上限，无法继续 search_chunks/search_chunks_batch。"
                            "可精读已有结果（read_chunks、read_neighbor_chunks），"
                            "证据足够时再 finish。"
                        )
                        chunks = []
                    elif planned_units > remaining:
                        observation, chunks, retrieval_units = await self.tools.execute(
                            db,
                            action,
                            action_input,
                            question=question,
                            doc_ids=doc_ids,
                            explicit_filters=filters,
                            retrieval_budget=remaining,
                        )
                        state.retrieval_calls += retrieval_units
                        if planned_units > remaining:
                            observation += (
                                f"\n（检索配额不足：计划 {planned_units} 路，"
                                f"仅执行 {retrieval_units} 路；"
                                f"后续请减少 searches 或改用 read_chunks 精读已有结果。）"
                            )
                    else:
                        observation, chunks, retrieval_units = await self.tools.execute(
                            db,
                            action,
                            action_input,
                            question=question,
                            doc_ids=doc_ids,
                            explicit_filters=filters,
                        )
                        state.retrieval_calls += retrieval_units
                else:
                    observation, chunks, _ = await self.tools.execute(
                        db,
                        action,
                        action_input,
                        question=question,
                        doc_ids=doc_ids,
                        explicit_filters=filters,
                    )
                state.tool_cache[cache_key] = observation

            if action in SEMANTIC_SEARCH_ACTIONS and retrieval_units > 0:
                state.semantic_search_units += retrieval_units

            merge_chunks_into_evidence(
                state.evidence,
                state.seen_evidence_keys,
                chunks,
                source_action=action,
            )

            step = AgentStep(
                step=step_num,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
                reasoning_content=reasoning_content,
            )
            state.steps.append(step)
            await self._emit_step(
                on_step,
                {
                    "type": "agent_step",
                    "step": step.step,
                    "thought": step.thought,
                    "reasoning": step.reasoning_content,
                    "action": step.action,
                    "action_input": step.action_input,
                    "observation": step.observation,
                    "evidence_count": len(state.evidence),
                },
            )

        if not state.done:
            state.done = True
            logger.info(
                "Agent reached max steps (%d); forcing synthesis",
                self.settings.rag_agent_max_steps,
            )

        fallback = resolve_retrieval_fallback(
            lang,
            evidence=state.evidence,
            settings=self.settings,
            reranker_active=self.rag.reranker is not None,
        )
        if fallback:
            logger.info(
                "Agent fallback: semantic_units=%d evidence=%d",
                state.semantic_search_units,
                len(state.evidence),
            )
            return AgentResult(
                answer=fallback,
                citations=[],
                language=lang,
                steps=state.steps,
                evidence=state.evidence,
                fallback_message=fallback,
            )

        if skip_synthesis:
            return AgentResult(
                answer="",
                citations=[],
                language=lang,
                steps=state.steps,
                evidence=state.evidence,
            )

        context = self.rag.build_context(state.evidence)
        vision_images = await prepare_vision_images(db, state.evidence, self.settings)
        use_vision = self.settings.llm_vision_enabled and bool(vision_images)
        if use_vision:
            answer = await self.llm.chat_vision(
                question, context, vision_images, chat_history, lang=lang
            )
        else:
            answer = await self.llm.chat(
                question,
                context,
                chat_history,
                include_embed_rules=evidence_has_visual(state.evidence),
                lang=lang,
            )
        answer, public_citations, embeds = finalize_answer(answer, state.evidence)

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
            embeds=embeds,
            language=lang,
            steps=state.steps,
            evidence=state.evidence,
        )
