import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import async_session_factory
from app.services.agent.state import (
    AgentResult,
    AgentState,
    AgentStep,
    AgentToolCall,
    OnAgentStep,
)
from app.services.agent.tools import (
    RETRIEVAL_QUOTA_MESSAGE,
    RETRIEVAL_TOOLS,
    AgentToolRegistry,
    count_retrieval_units,
    merge_chunks_into_evidence,
    parse_finish_key_evidence_ids,
    prioritize_evidence,
)
from app.services.chunk_filter import ChunkFilter
from app.services.llm import LLMService

from app.services.rag import RAGService, detect_language, resolve_retrieval_fallback

logger = logging.getLogger(__name__)

TERMINAL_ACTIONS = frozenset({"finish", "ask_user"})


def _evidence_for_synthesis(state: AgentState) -> list[dict]:
    finish_step = next(
        (step for step in reversed(state.steps) if step.action == "finish"),
        None,
    )
    if finish_step is None:
        return state.evidence
    key_ids = parse_finish_key_evidence_ids(finish_step.action_input)
    return prioritize_evidence(state.evidence, key_ids)


def _normalize_actions(action_payload: dict) -> list[dict]:
    actions = action_payload.get("actions")
    if isinstance(actions, list) and actions:
        normalized: list[dict] = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            if not action:
                continue
            action_input = item.get("action_input")
            if not isinstance(action_input, dict):
                action_input = {}
            normalized.append(
                {
                    "action": action,
                    "action_input": action_input,
                    "tool_call_id": str(item.get("tool_call_id") or ""),
                }
            )
        if normalized:
            return normalized
    action = str(action_payload.get("action") or "finish").strip()
    action_input = action_payload.get("action_input")
    if not isinstance(action_input, dict):
        action_input = {}
    return [
        {
            "action": action,
            "action_input": action_input,
            "tool_call_id": "",
        }
    ]


def _display_action(actions: list[dict]) -> str:
    if len(actions) == 1:
        return actions[0]["action"]
    return " + ".join(item["action"] for item in actions)


def _display_action_input(actions: list[dict]) -> dict:
    if len(actions) == 1:
        return actions[0]["action_input"]
    return {
        "calls": [
            {"action": item["action"], "action_input": item["action_input"]}
            for item in actions
        ]
    }


def _join_observations(tool_calls: list[AgentToolCall]) -> str:
    if len(tool_calls) == 1:
        return tool_calls[0].observation
    parts = [
        f"工具 {index}：{call.action}\n{call.observation}"
        for index, call in enumerate(tool_calls, start=1)
    ]
    return "\n\n---\n\n".join(parts)


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
        *,
        lang: str | None = None,
    ) -> AsyncIterator[str]:
        context = self.rag.build_context(evidence)
        response_lang = lang or detect_language(question)
        async for delta in self.llm.chat_stream(
            question,
            context,
            chat_history,
            lang=response_lang,
        ):
            yield delta

    async def _execute_one_tool(
        self,
        db: AsyncSession,
        *,
        action: str,
        action_input: dict,
        question: str,
        doc_ids: list[UUID] | None,
        filters: ChunkFilter | None,
        retrieval_budget: int | None = None,
    ) -> tuple[str, list[dict], int]:
        if action in RETRIEVAL_TOOLS and retrieval_budget is not None and retrieval_budget <= 0:
            return RETRIEVAL_QUOTA_MESSAGE, [], 0

        budget: int | None = None
        if action in RETRIEVAL_TOOLS and retrieval_budget is not None:
            planned_units = count_retrieval_units(
                action,
                action_input,
                max_batch=self.settings.rag_batch_search_max,
            )
            if planned_units > retrieval_budget:
                budget = retrieval_budget

        observation, chunks, retrieval_units = await self.tools.execute(
            db,
            action,
            action_input,
            question=question,
            doc_ids=doc_ids,
            explicit_filters=filters,
            retrieval_budget=budget,
        )

        if (
            action in RETRIEVAL_TOOLS
            and budget is not None
            and retrieval_budget is not None
        ):
            planned_units = count_retrieval_units(
                action,
                action_input,
                max_batch=self.settings.rag_batch_search_max,
            )
            if planned_units > retrieval_budget:
                observation += (
                    f"\n（检索配额不足：计划 {planned_units} 路，"
                    f"仅执行 {retrieval_units} 路；"
                    f"后续请减少 searches 或改用 read_neighbor_chunks 扩展上下文。）"
                )

        return observation, chunks, retrieval_units if action in RETRIEVAL_TOOLS else 0

    async def _execute_tool_batch(
        self,
        state: AgentState,
        actions: list[dict],
        *,
        question: str,
        doc_ids: list[UUID] | None,
        filters: ChunkFilter | None,
    ) -> list[AgentToolCall]:
        valid_actions = [
            item
            for item in actions
            if item["action"] not in TERMINAL_ACTIONS
        ][: self.settings.rag_agent_max_parallel_tools]
        if not valid_actions:
            return []

        max_batch = self.settings.rag_batch_search_max
        remaining = self.settings.rag_agent_max_retrievals - state.retrieval_calls
        retrieval_actions = [
            item for item in valid_actions if item["action"] in RETRIEVAL_TOOLS
        ]
        total_planned = sum(
            count_retrieval_units(
                item["action"],
                item["action_input"],
                max_batch=max_batch,
            )
            for item in retrieval_actions
        )
        use_parallel = not retrieval_actions or total_planned <= remaining

        async def run_item(
            item: dict,
            *,
            tool_db: AsyncSession,
            retrieval_budget: int | None,
        ) -> tuple[AgentToolCall, list[dict], int]:
            action = item["action"]
            action_input = item["action_input"]
            tool_call_id = item["tool_call_id"]
            cache_key = self.tools.cache_key(action, action_input)
            if cache_key in state.tool_cache:
                return (
                    AgentToolCall(
                        action=action,
                        action_input=action_input,
                        observation=state.tool_cache[cache_key],
                        tool_call_id=tool_call_id,
                    ),
                    [],
                    0,
                )

            observation, chunks, retrieval_units = await self._execute_one_tool(
                tool_db,
                action=action,
                action_input=action_input,
                question=question,
                doc_ids=doc_ids,
                filters=filters,
                retrieval_budget=retrieval_budget,
            )
            return (
                AgentToolCall(
                    action=action,
                    action_input=action_input,
                    observation=observation,
                    tool_call_id=tool_call_id,
                ),
                chunks,
                retrieval_units,
            )

        async def run_item_with_session(
            item: dict,
            *,
            retrieval_budget: int | None,
        ) -> tuple[AgentToolCall, list[dict], int]:
            async with async_session_factory() as tool_db:
                return await run_item(
                    item,
                    tool_db=tool_db,
                    retrieval_budget=retrieval_budget,
                )

        results: list[tuple[AgentToolCall, list[dict], int]] = []
        if use_parallel:
            gathered = await asyncio.gather(
                *[
                    run_item_with_session(item, retrieval_budget=None)
                    for item in valid_actions
                ]
            )
            results = list(gathered)
        else:
            budget_left = remaining
            for item in valid_actions:
                budget: int | None = None
                if item["action"] in RETRIEVAL_TOOLS:
                    if budget_left <= 0:
                        results.append(
                            (
                                AgentToolCall(
                                    action=item["action"],
                                    action_input=item["action_input"],
                                    observation=RETRIEVAL_QUOTA_MESSAGE,
                                    tool_call_id=item["tool_call_id"],
                                ),
                                [],
                                0,
                            )
                        )
                        continue
                    planned_units = count_retrieval_units(
                        item["action"],
                        item["action_input"],
                        max_batch=max_batch,
                    )
                    if planned_units > budget_left:
                        budget = budget_left
                tool_call, chunks, retrieval_units = await run_item_with_session(
                    item,
                    retrieval_budget=budget,
                )
                results.append((tool_call, chunks, retrieval_units))
                budget_left -= retrieval_units

        tool_calls: list[AgentToolCall] = []
        for tool_call, chunks, retrieval_units in results:
            cache_key = self.tools.cache_key(
                tool_call.action,
                tool_call.action_input,
            )
            state.tool_cache.setdefault(cache_key, tool_call.observation)
            state.retrieval_calls += retrieval_units
            if tool_call.action in RETRIEVAL_TOOLS and retrieval_units > 0:
                state.semantic_search_units += retrieval_units
            merge_chunks_into_evidence(
                state.evidence,
                state.seen_evidence_keys,
                chunks,
                source_action=tool_call.action,
            )
            tool_calls.append(tool_call)
        return tool_calls

    async def run(
        self,
        question: str,
        doc_ids: list[UUID] | None = None,
        filters: ChunkFilter | None = None,
        *,
        on_step: OnAgentStep | None = None,
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
                question,
                state.steps,
                evidence=state.evidence,
                lang=lang,
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
            actions = _normalize_actions(action_payload)
            actions = actions[: self.settings.rag_agent_max_parallel_tools]
            action = _display_action(actions)
            action_input = _display_action_input(actions)

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

            if any(item["action"] == "ask_user" for item in actions):
                ask_item = next(
                    item for item in actions if item["action"] == "ask_user"
                )
                state.done = True
                clarification = str(
                    ask_item["action_input"].get("question") or ""
                ).strip()
                step = AgentStep(
                    step=step_num,
                    thought=thought,
                    action="ask_user",
                    action_input=ask_item["action_input"],
                    observation="等待用户补充信息。",
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
                return AgentResult(
                    answer="",
                    citations=[],
                    language=lang,
                    steps=state.steps,
                    evidence=state.evidence,
                    clarification=clarification or None,
                )

            if any(item["action"] == "finish" for item in actions):
                finish_item = next(
                    item for item in actions if item["action"] == "finish"
                )
                state.done = True
                step = AgentStep(
                    step=step_num,
                    thought=thought,
                    action="finish",
                    action_input=finish_item["action_input"],
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

            tool_calls = await self._execute_tool_batch(
                state,
                actions,
                question=question,
                doc_ids=doc_ids,
                filters=filters,
            )
            observation = _join_observations(tool_calls)

            step = AgentStep(
                step=step_num,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls,
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

        evidence = _evidence_for_synthesis(state)
        return AgentResult(
            answer="",
            citations=[],
            language=lang,
            steps=state.steps,
            evidence=evidence,
        )
