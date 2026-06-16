"""Prepare page images for vision LLM synthesis."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Document
from app.services.page_render import render_page_png
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

_TYPE_PRIORITY = {"table": 0, "figure": 1, "text": 2, "page": 3}


@dataclass(frozen=True)
class VisionImage:
    ref_index: int
    document_id: str
    document_name: str
    page: int
    asset_type: str
    base64: str
    media_type: str


def _asset_type(chunk_type: str | None, asset_type: str | None = None) -> str:
    if asset_type:
        return asset_type
    if chunk_type == "table":
        return "table"
    if chunk_type == "figure":
        return chunk_type
    return "page"


def select_evidence_for_vision(
    evidence: list[dict],
    max_images: int,
) -> list[tuple[int, dict]]:
    """Return (1-based ref_index, chunk) pairs for vision input."""
    candidates: list[tuple[int, int, str, dict]] = []
    seen_keys: set[str] = set()

    for index, chunk in enumerate(evidence, start=1):
        assets = chunk.get("assets") or []
        document_id = chunk.get("document_id")
        page = chunk.get("page")
        if assets:
            dedupe_key = f"asset:{assets[0]['asset_id']}"
        elif page and document_id:
            dedupe_key = f"page:{document_id}:{page}"
        else:
            continue
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        chunk_type = chunk.get("chunk_type") or "text"
        has_asset = bool(assets)
        priority = _TYPE_PRIORITY.get(chunk_type, 99) - (1 if has_asset else 0)
        candidates.append((priority, index, dedupe_key, chunk))

    candidates.sort(key=lambda item: (item[0], item[1]))
    return [(index, chunk) for _, index, _, chunk in candidates[:max_images]]


def _load_png_bytes(
    storage: StorageService,
    settings: Settings,
    file_cache: dict[str, tuple[bytes, str]],
    chunk: dict,
) -> tuple[bytes, str]:
    document_id = str(chunk["document_id"])
    page = int(chunk["page"]) if chunk.get("page") else 1
    assets = chunk.get("assets") or []

    if assets and assets[0].get("object_key"):
        return storage.download(assets[0]["object_key"]), "image/png"

    file_bytes, filename = file_cache[document_id]
    png_bytes = render_page_png(
        file_bytes,
        filename,
        page,
        scale=settings.llm_vision_render_scale,
    )
    ext = filename.rsplit(".", 1)[-1].lower()
    media_type = "image/png" if ext == "pdf" else f"image/{ext if ext != 'jpg' else 'jpeg'}"
    return png_bytes, media_type


async def _render_vision_image(
    storage: StorageService,
    settings: Settings,
    file_cache: dict[str, tuple[bytes, str]],
    ref_index: int,
    chunk: dict,
) -> VisionImage | None:
    document_id = str(chunk["document_id"])
    page = int(chunk["page"]) if chunk.get("page") else 1
    assets = chunk.get("assets") or []
    needs_document = not (assets and assets[0].get("object_key"))
    if needs_document and document_id not in file_cache:
        return None

    try:
        png_bytes, media_type = await asyncio.to_thread(
            _load_png_bytes,
            storage,
            settings,
            file_cache,
            chunk,
        )
        return VisionImage(
            ref_index=ref_index,
            document_id=document_id,
            document_name=str(chunk.get("document_name") or ""),
            page=page,
            asset_type=_asset_type(
                chunk.get("chunk_type"),
                assets[0].get("type") if assets else None,
            ),
            base64=base64.b64encode(png_bytes).decode("ascii"),
            media_type=media_type,
        )
    except Exception:
        logger.warning(
            "Failed to render vision image for doc=%s page=%s",
            document_id,
            page,
            exc_info=True,
        )
        return None


async def prepare_vision_images(
    db: AsyncSession,
    evidence: list[dict],
    settings: Settings | None = None,
) -> list[VisionImage]:
    settings = settings or get_settings()
    if not settings.llm_vision_enabled or not evidence:
        return []

    selected = select_evidence_for_vision(evidence, settings.llm_vision_max_images)
    if not selected:
        return []

    storage = StorageService(settings)
    file_cache: dict[str, tuple[bytes, str]] = {}

    doc_ids_to_load: set[str] = set()
    for _, chunk in selected:
        assets = chunk.get("assets") or []
        if not (assets and assets[0].get("object_key")):
            doc_ids_to_load.add(str(chunk["document_id"]))

    async def _download_document(doc_id: str) -> tuple[str, tuple[bytes, str]] | None:
        document = await db.get(Document, uuid.UUID(doc_id))
        if not document:
            return None
        file_bytes = await asyncio.to_thread(storage.download, document.object_key)
        return doc_id, (file_bytes, document.name)

    if doc_ids_to_load:
        downloads = await asyncio.gather(*(_download_document(doc_id) for doc_id in doc_ids_to_load))
        for item in downloads:
            if item is not None:
                doc_id, payload = item
                file_cache[doc_id] = payload

    images = await asyncio.gather(
        *(
            _render_vision_image(storage, settings, file_cache, ref_index, chunk)
            for ref_index, chunk in selected
        )
    )
    return [image for image in images if image is not None]
