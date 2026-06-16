import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.services.agent.fast_path import detect_fast_path
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
    ) -> AsyncIterator[str]:
        context = self.rag.build_context(evidence)
        use_vision = (
            self.settings.llm_vision_enabled
            and vision_images
        )
        stream = (
            self.llm.chat_stream_vision(question, context, vision_images, chat_history)
            if use_vision
            else self.llm.chat_stream(question, context, chat_history)
        )
        async for delta in stream:
            yield delta

    async def _run_fast_path(
        self,
        db: AsyncSession,
        question: str,
        state: AgentState,
        *,
        doc_ids: list[UUID] | None,
        filters: ChunkFilter | None,
        on_step: OnAgentStep | None,
    ) -> bool:
        detected = detect_fast_path(question)
        if detected is None:
            return False

        action, action_input = detected
        thought = f"快速路径：{action}"
        await self._emit_step(
            on_step,
            {
                "type": "agent_step_start",
                "step": 1,
                "thought": thought,
                "action": action,
                "action_input": action_input,
            },
        )

        observation, chunks, retrieval_units = await self.tools.execute(
            db,
            action,
            action_input,
            question=question,
            doc_ids=doc_ids,
            explicit_filters=filters,
        )
        if action in RETRIEVAL_TOOLS:
            state.retrieval_calls += retrieval_units
        if action in SEMANTIC_SEARCH_ACTIONS and retrieval_units > 0:
            state.semantic_search_units += retrieval_units

        merge_chunks_into_evidence(
            state.evidence,
            state.seen_evidence_keys,
            chunks,
            source_action=action,
        )

        step = AgentStep(
            step=1,
            thought=thought,
            action=action,
            action_input=action_input,
            observation=observation,
        )
        state.steps.append(step)
        state.done = True
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
        logger.info("Agent fast path: action=%s evidence=%d", action, len(state.evidence))
        return True

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

        if not await self._run_fast_path(
            db,
            question,
            state,
            doc_ids=doc_ids,
            filters=filters,
            on_step=on_step,
        ):
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

                action_payload = await self.llm.decide_agent_action(question, state.steps)
                thought = str(action_payload.get("thought") or "")
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
                            observation = "检索次数已达上限，请调用 finish。"
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
                                    f"仅执行 {retrieval_units} 路，请 finish 或换更少的 searches。）"
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
                logger.info(
                    "Agent reached max steps (%d); forcing synthesis",
                    self.settings.rag_agent_max_steps,
                )

        fallback = resolve_retrieval_fallback(
            lang,
            evidence=state.evidence,
            settings=self.settings,
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
        if self.settings.llm_vision_enabled and vision_images:
            answer = await self.llm.chat_vision(
                question, context, vision_images, chat_history
            )
        else:
            answer = await self.llm.chat(question, context, chat_history)
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
