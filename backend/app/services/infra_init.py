"""One-time initialization for external stores (MinIO, Qdrant, Elasticsearch)."""

from __future__ import annotations

import asyncio
import logging

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def ensure_external_stores(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    from app.services.fulltext_store import ensure_index
    from app.services.storage import ensure_bucket
    from app.services.vector_store import ensure_collection

    ensure_bucket(settings)
    ensure_collection(settings)
    if settings.hybrid_enabled:
        ensure_index(settings)
    logger.info("External stores ready")


async def ensure_external_stores_async(settings: Settings | None = None) -> None:
    await asyncio.to_thread(ensure_external_stores, settings)
