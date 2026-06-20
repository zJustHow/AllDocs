"""Legacy post-parse VLM captions. Primary routing runs during PDF parse via pdf_vlm_route."""

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
        result = caption_service.classify_and_describe(job.image_bytes, media_type=job.media_type)
        return result.caption if result else None
    except Exception:
        logger.warning("Asset caption job failed", exc_info=True)
        return None


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
    """Backfill vlm_caption for assets missed during parse (e.g. PyMuPDF vector tables)."""
    if not settings.ingest_caption_enabled:
        return 0

    asset_rows = (
        db.query(ChunkAsset)
        .filter(ChunkAsset.document_id == document.id)
        .order_by(ChunkAsset.page)
        .all()
    )
    planned = [asset for asset in asset_rows if not asset.vlm_caption]
    if not planned:
        return 0

    caption_service = CaptionService(settings)
    storage = StorageService(settings)
    generated = 0
    workers = min(_CAPTION_WORKERS, len(planned))
    per_page_counts: dict[int, int] = {}
    max_per_page = max(1, settings.ingest_caption_max_per_page)

    def _caption_asset(asset: ChunkAsset) -> tuple[ChunkAsset, str | None]:
        job = _resolve_asset_image(
            asset,
            storage=storage,
            asset_image_bytes=asset_image_bytes,
        )
        return asset, _run_caption_job(caption_service, job)

    eligible: list[ChunkAsset] = []
    for asset in planned:
        count = per_page_counts.get(asset.page, 0)
        if count >= max_per_page:
            continue
        per_page_counts[asset.page] = count + 1
        eligible.append(asset)

    if not eligible:
        return 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_caption_asset, asset) for asset in eligible]
        for future in as_completed(futures):
            target, caption = future.result()
            if not caption:
                continue
            target.vlm_caption = caption
            generated += 1

    if generated:
        db.flush()
    return generated
