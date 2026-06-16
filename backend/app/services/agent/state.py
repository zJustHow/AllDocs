from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.services.llm import QueryIntent

OnAgentStep = Callable[[dict], Awaitable[None] | None]


@dataclass
class AgentStep:
    step: int
    thought: str
    action: str
    action_input: dict
    observation: str


@dataclass
class AgentResult:
    answer: str
    citations: list[dict]
    intent: QueryIntent
    language: str
    steps: list[AgentStep]
    evidence: list[dict]


@dataclass
class AgentState:
    steps: list[AgentStep] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    seen_evidence_keys: set[str] = field(default_factory=set)
    retrieval_calls: int = 0
    done: bool = False
    intent: QueryIntent = "general"
    tool_cache: dict[str, str] = field(default_factory=dict)
