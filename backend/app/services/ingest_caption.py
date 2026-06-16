"""Apply VLM captions to chunks and assets during ingestion."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session as OrmSession

from app.config import Settings
from app.db.models import Chunk, ChunkAsset, Document
from app.services.caption import CaptionService
from app.services.chunk_index import merge_visual_descriptions_into_text
from app.services.file_types import detect_file_type
from app.services.page_render import render_page_png
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_CAPTION_WORKERS = 3


def _image_media_type(filename: str) -> str:
    ext = detect_file_type(filename)
    if ext is None:
        return "image/png"
    if ext.extension == ".jpg":
        return "image/jpeg"
    return ext.content_type


@dataclass(frozen=True)
class _CaptionJob:
    kind: Literal["asset", "chunk"]
    image_bytes: bytes
    media_type: str = "image/png"


def _run_caption_job(caption_service: CaptionService, job: _CaptionJob) -> str | None:
    try:
        return caption_service.caption_image(job.image_bytes, media_type=job.media_type)
    except Exception:
        logger.warning("Caption job failed (%s)", job.kind, exc_info=True)
        return None


def _build_caption_jobs(
    *,
    asset_rows: list[ChunkAsset],
    chunk_rows: list[Chunk],
    assets_by_chunk: dict[str, list[ChunkAsset]],
    file_bytes: bytes,
    filename: str,
    settings: Settings,
    is_image_doc: bool,
    min_chars: int,
    max_count: int,
) -> list[tuple[ChunkAsset | Chunk, _CaptionJob]]:
    jobs: list[tuple[ChunkAsset | Chunk, _CaptionJob]] = []
    image_media_type = _image_media_type(filename)

    for asset in asset_rows:
        if len(jobs) >= max_count:
            break
        jobs.append(
            (
                asset,
                _CaptionJob(kind="asset", image_bytes=b"", media_type="image/png"),
            )
        )

    for chunk in chunk_rows:
        if len(jobs) >= max_count:
            break
        if assets_by_chunk.get(str(chunk.id)):
            continue
        text_len = len(chunk.text.strip())
        if not is_image_doc and text_len >= min_chars:
            continue
        if is_image_doc:
            jobs.append(
                (
                    chunk,
                    _CaptionJob(
                        kind="chunk",
                        image_bytes=file_bytes,
                        media_type=image_media_type,
                    ),
                )
            )
        elif chunk.page is not None:
            jobs.append(
                (
                    chunk,
                    _CaptionJob(kind="chunk", image_bytes=b"", media_type="image/png"),
                )
            )

    return jobs


def _resolve_job_image(
    job: _CaptionJob,
    *,
    storage: StorageService,
    asset: ChunkAsset | None,
    asset_image_bytes: dict[str, bytes] | None,
    file_bytes: bytes,
    filename: str,
    chunk: Chunk | None,
    settings: Settings,
) -> _CaptionJob:
    if job.image_bytes:
        return job
    if asset is not None:
        cached = (asset_image_bytes or {}).get(str(asset.id))
        if cached is not None:
            return _CaptionJob(kind="asset", image_bytes=cached, media_type="image/png")
        return _CaptionJob(
            kind="asset",
            image_bytes=storage.download(asset.object_key),
            media_type="image/png",
        )
    if chunk is not None and chunk.page is not None:
        return _CaptionJob(
            kind="chunk",
            image_bytes=render_page_png(
                file_bytes,
                filename,
                int(chunk.page),
                scale=settings.llm_vision_render_scale,
            ),
            media_type="image/png",
        )
    raise ValueError("caption job has no image source")


def apply_ingest_captions(
    db: OrmSession,
    *,
    document: Document,
    chunk_rows: list[Chunk],
    file_bytes: bytes,
    filename: str,
    settings: Settings,
    asset_image_bytes: dict[str, bytes] | None = None,
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
    max_count = settings.ingest_caption_max_per_doc
    min_chars = settings.ingest_caption_min_text_chars
    file_type = detect_file_type(filename)
    is_image_doc = file_type is not None and file_type.extension in _IMAGE_EXTENSIONS

    planned = _build_caption_jobs(
        asset_rows=asset_rows,
        chunk_rows=chunk_rows,
        assets_by_chunk=assets_by_chunk,
        file_bytes=file_bytes,
        filename=filename,
        settings=settings,
        is_image_doc=is_image_doc,
        min_chars=min_chars,
        max_count=max_count,
    )
    if not planned:
        return 0

    generated = 0
    workers = min(_CAPTION_WORKERS, len(planned))

    def _caption_target(target: ChunkAsset | Chunk, job: _CaptionJob) -> tuple[ChunkAsset | Chunk, str | None]:
        asset = target if isinstance(target, ChunkAsset) else None
        chunk = target if isinstance(target, Chunk) else None
        resolved = _resolve_job_image(
            job,
            storage=storage,
            asset=asset,
            asset_image_bytes=asset_image_bytes,
            file_bytes=file_bytes,
            filename=filename,
            chunk=chunk,
            settings=settings,
        )
        return target, _run_caption_job(caption_service, resolved)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_caption_target, target, job) for target, job in planned]
        for future in as_completed(futures):
            target, caption = future.result()
            if not caption:
                continue
            if isinstance(target, ChunkAsset):
                target.caption = caption
            else:
                target.caption = caption
            generated += 1

    if generated:
        db.flush()
    return generated


def merge_captions_into_chunk_text(
    db: OrmSession,
    *,
    chunk_rows: list[Chunk],
    assets_by_chunk: dict[str, list[ChunkAsset]],
    settings: Settings,
) -> int:
    """Merge table/figure VLM captions into chunk.text; clear chunk.caption after merge."""
    updated = 0
    min_body_chars = settings.ingest_caption_min_text_chars
    for chunk in chunk_rows:
        assets = assets_by_chunk.get(str(chunk.id), [])
        merged = merge_visual_descriptions_into_text(
            chunk.text,
            chunk_caption=chunk.caption,
            assets=assets,
            replace_short_body=True,
            min_body_chars=min_body_chars,
        )
        if merged == chunk.text and not chunk.caption:
            continue
        chunk.text = merged
        if chunk.caption:
            chunk.caption = None
        updated += 1
    if updated:
        db.flush()
    return updated
