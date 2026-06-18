from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

OnAgentStep = Callable[[dict], Awaitable[None] | None]


@dataclass
class AgentStep:
    step: int
    thought: str
    action: str
    action_input: dict
    observation: str
    reasoning_content: str = ""


@dataclass
class AgentResult:
    answer: str
    citations: list[dict]
    language: str
    steps: list[AgentStep]
    evidence: list[dict]
    embeds: list[dict] = field(default_factory=list)
    fallback_message: str | None = None
    clarification: str | None = None


@dataclass
class AgentState:
    steps: list[AgentStep] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    seen_evidence_keys: set[str] = field(default_factory=set)
    retrieval_calls: int = 0
    semantic_search_units: int = 0
    done: bool = False
    tool_cache: dict[str, str] = field(default_factory=dict)
