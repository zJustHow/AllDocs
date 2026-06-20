"""Attach visual assets to preceding text chunks by document reading order."""

from __future__ import annotations

from collections.abc import Callable

_MAX_FALLBACK_PAGE_GAP = 2
_SAME_PAGE_Y_TOLERANCE_PT = 4.0

BlockSpan = tuple[int, int, float, float]


def _is_attach_candidate(chunk: object) -> bool:
    page = getattr(chunk, "page", None)
    if page is None:
        return False
    return bool(getattr(chunk, "text", "").strip())


def _chunk_sort_key(chunk: object) -> float | None:
    sort_key = getattr(chunk, "sort_key", None)
    if sort_key is not None:
        return float(sort_key)
    bbox = getattr(chunk, "layout_bbox", None)
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 2:
        return float(bbox[1])
    return None


def _chunk_end_y(chunk: object) -> float | None:
    layout_y1 = getattr(chunk, "layout_y1", None)
    if layout_y1 is not None:
        return float(layout_y1)
    bbox = getattr(chunk, "layout_bbox", None)
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return float(bbox[3])
    return None


def _asset_top_y(
    *,
    asset_bbox: tuple[float, float, float, float] | None,
    asset_sort_key: float | None,
) -> float | None:
    if asset_sort_key is not None:
        return float(asset_sort_key)
    if asset_bbox is not None and len(asset_bbox) >= 2:
        return float(asset_bbox[1])
    return None


def _pick_same_page_spatial(
    pool: list,
    *,
    page: int,
    asset_top_y: float,
) -> object | None:
    """Return the text chunk whose bottom edge is closest above the asset."""
    above: list[tuple[float, float, int, object]] = []
    for chunk in pool:
        if int(getattr(chunk, "page")) != page:
            continue
        end_y = _chunk_end_y(chunk)
        if end_y is None:
            continue
        if end_y > asset_top_y + _SAME_PAGE_Y_TOLERANCE_PT:
            continue
        start_y = _chunk_sort_key(chunk)
        if start_y is not None and start_y > asset_top_y + _SAME_PAGE_Y_TOLERANCE_PT:
            continue
        above.append(
            (
                end_y,
                start_y if start_y is not None else end_y,
                int(getattr(chunk, "chunk_index", 0)),
                chunk,
            )
        )
    if not above:
        return None
    return max(above, key=lambda item: (item[0], item[1], item[2]))[3]


def _pick_latest_chunk(pool: list) -> object:
    return max(
        pool,
        key=lambda chunk: (
            int(getattr(chunk, "page")),
            int(getattr(chunk, "chunk_index", 0)),
        ),
    )


def pick_preceding_chunk(
    chunks: list,
    *,
    page: int,
    section: str | None,
    asset_bbox: tuple[float, float, float, float] | None = None,
    asset_sort_key: float | None = None,
    max_page_gap: int = _MAX_FALLBACK_PAGE_GAP,
) -> object | None:
    """Return the best preceding text chunk for a visual asset within ``max_page_gap`` pages."""
    pool = [
        chunk
        for chunk in chunks
        if _is_attach_candidate(chunk)
        and int(getattr(chunk, "page")) <= page
        and page - int(getattr(chunk, "page")) <= max_page_gap
    ]
    if not pool:
        return None

    if section:
        section_pool = [chunk for chunk in pool if chunk.section == section]
        if section_pool:
            pool = section_pool

    asset_top_y = _asset_top_y(asset_bbox=asset_bbox, asset_sort_key=asset_sort_key)
    if asset_top_y is not None:
        same_page_target = _pick_same_page_spatial(pool, page=page, asset_top_y=asset_top_y)
        if same_page_target is not None:
            return same_page_target

        earlier_pages = [chunk for chunk in pool if int(getattr(chunk, "page")) < page]
        if earlier_pages:
            return _pick_latest_chunk(earlier_pages)
        return None

    return _pick_latest_chunk(pool)


def attach_assets_by_reading_order(
    assets: list,
    chunks: list,
    *,
    to_attached_asset: Callable[[object], object],
    should_skip: Callable[[object, list], bool] | None = None,
) -> list:
    """Attach assets to preceding text chunks by reading order; return orphans."""
    if not assets:
        return []

    orphans: list = []
    for asset in sorted(assets, key=lambda item: (item.page, item.sort_key)):
        if should_skip is not None and should_skip(asset, chunks):
            continue

        target = pick_preceding_chunk(
            chunks,
            page=asset.page,
            section=asset.section,
            asset_bbox=asset.bbox,
            asset_sort_key=asset.sort_key,
        )
        if target is None:
            orphans.append(asset)
            continue
        target.attached_assets.append(to_attached_asset(asset))

    return orphans
