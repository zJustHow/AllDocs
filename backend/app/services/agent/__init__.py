from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.agent.service import AgentRAGService

__all__ = ["AgentRAGService"]


def __getattr__(name: str):
    if name == "AgentRAGService":
        from app.services.agent.service import AgentRAGService

        return AgentRAGService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
