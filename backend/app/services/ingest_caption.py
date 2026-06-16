"""Apply VLM captions to chunks and assets during ingestion."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session as OrmSession

from app.config import Settings
from app.db.models import Chunk, ChunkAsset, Document
from app.services.caption import CaptionService
from app.services.file_types import detect_file_type
from app.services.page_render import render_page_png
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def _image_media_type(filename: str) -> str:
    ext = detect_file_type(filename)
    if ext is None:
        return "image/png"
    if ext.extension == ".jpg":
        return "image/jpeg"
    return ext.content_type


def apply_ingest_captions(
    db: OrmSession,
    *,
    document: Document,
    chunk_rows: list[Chunk],
    file_bytes: bytes,
    filename: str,
    settings: Settings,
) -> int:
    if not settings.ingest_caption_enabled:
        return 0

    asset_rows = (
        db.query(ChunkAsset)
        .filter(ChunkAsset.document_id == document.id)
        .order_by(ChunkAsset.page)
        .all()
    )
    assets_by_chunk: dict[str, list[ChunkAsset]] = {}
    for asset in asset_rows:
        assets_by_chunk.setdefault(str(asset.chunk_id), []).append(asset)

    caption_service = CaptionService(settings)
    storage = StorageService(settings)
    generated = 0
    max_count = settings.ingest_caption_max_per_doc
    min_chars = settings.ingest_caption_min_text_chars
    file_type = detect_file_type(filename)
    is_image_doc = file_type is not None and file_type.extension in _IMAGE_EXTENSIONS

    for asset in asset_rows:
        if generated >= max_count:
            break
        try:
            png_bytes = storage.download(asset.object_key)
            asset.caption = caption_service.caption_image(png_bytes)
            generated += 1
        except Exception:
            logger.warning(
                "Caption failed for asset %s doc=%s",
                asset.id,
                document.id,
                exc_info=True,
            )

    for chunk in chunk_rows:
        if generated >= max_count:
            break
        if assets_by_chunk.get(str(chunk.id)):
            continue
        text_len = len(chunk.text.strip())
        if not is_image_doc and text_len >= min_chars:
            continue
        try:
            if is_image_doc:
                chunk.caption = caption_service.caption_image(
                    file_bytes,
                    media_type=_image_media_type(filename),
                )
            elif chunk.page is not None:
                png_bytes = render_page_png(
                    file_bytes,
                    filename,
                    int(chunk.page),
                    scale=settings.llm_vision_render_scale,
                )
                chunk.caption = caption_service.caption_image(png_bytes)
            else:
                continue
            generated += 1
        except Exception:
            logger.warning(
                "Caption failed for chunk %s doc=%s",
                chunk.id,
                document.id,
                exc_info=True,
            )

    if generated:
        db.flush()
    return generated
