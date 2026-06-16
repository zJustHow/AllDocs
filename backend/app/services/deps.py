from functools import lru_cache

from app.config import get_settings
from app.services.agent import AgentRAGService


@lru_cache
def get_agent_service() -> AgentRAGService:
    return AgentRAGService(get_settings())
