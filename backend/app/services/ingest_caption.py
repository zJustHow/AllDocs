"""Apply VLM captions to visual assets during ingestion."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from sqlalchemy.orm import Session as OrmSession

from app.config import Settings
from app.db.models import ChunkAsset, Document
from app.services.caption import CaptionService
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

_CAPTION_WORKERS = 3


@dataclass(frozen=True)
class _CaptionJob:
    image_bytes: bytes
    media_type: str = "image/png"


def _run_caption_job(caption_service: CaptionService, job: _CaptionJob) -> str | None:
    try:
        return caption_service.caption_image(job.image_bytes, media_type=job.media_type)
    except Exception:
        logger.warning("Asset caption job failed", exc_info=True)
        return None


def _build_caption_jobs(
    asset_rows: list[ChunkAsset],
    *,
    max_count: int,
) -> list[ChunkAsset]:
    planned: list[ChunkAsset] = []
    seen_asset_ids: set[uuid.UUID] = set()

    for asset in asset_rows:
        if len(planned) >= max_count:
            break
        if asset.id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset.id)
        planned.append(asset)

    return planned


def _resolve_asset_image(
    asset: ChunkAsset,
    *,
    storage: StorageService,
    asset_image_bytes: dict[str, bytes] | None,
) -> _CaptionJob:
    cached = (asset_image_bytes or {}).get(str(asset.id))
    if cached is not None:
        return _CaptionJob(image_bytes=cached, media_type="image/png")
    return _CaptionJob(
        image_bytes=storage.download(asset.object_key),
        media_type="image/png",
    )


def apply_ingest_captions(
    db: OrmSession,
    *,
    document: Document,
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
    planned = _build_caption_jobs(
        asset_rows,
        max_count=settings.ingest_caption_max_per_doc,
    )
    if not planned:
        return 0

    caption_service = CaptionService(settings)
    storage = StorageService(settings)
    generated = 0
    workers = min(_CAPTION_WORKERS, len(planned))

    def _caption_asset(asset: ChunkAsset) -> tuple[ChunkAsset, str | None]:
        job = _resolve_asset_image(
            asset,
            storage=storage,
            asset_image_bytes=asset_image_bytes,
        )
        return asset, _run_caption_job(caption_service, job)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_caption_asset, asset) for asset in planned]
        for future in as_completed(futures):
            target, caption = future.result()
            if not caption:
                continue
            for asset in asset_rows:
                if asset.id == target.id:
                    asset.caption = caption
                    break
            generated += 1

    if generated:
        db.flush()
    return generated
