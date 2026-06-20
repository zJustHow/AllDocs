"""Layout region helpers for visual PDF assets."""

from __future__ import annotations

from typing import Any


def layout_region(
    page: int,
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    return {"page": int(page), "bbox": [float(value) for value in bbox]}


def normalize_layout_regions(
    items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not items:
        return []

    resolved: list[dict[str, Any]] = []
    for item in items:
        page = item.get("page")
        bbox = item.get("bbox")
        if page is None or not bbox or len(bbox) != 4:
            continue
        resolved.append(
            {"page": int(page), "bbox": [float(value) for value in bbox]}
        )
    return resolved


def layout_regions_for_asset(
    *,
    page: int,
    bbox: tuple[float, float, float, float],
    layout_regions: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    regions = normalize_layout_regions(layout_regions)
    if regions:
        return regions
    return [layout_region(page, bbox)]


def resolve_asset_regions(asset: dict[str, Any]) -> list[dict[str, Any]]:
    regions = normalize_layout_regions(asset.get("layout_regions"))
    if regions:
        return regions

    page = asset.get("page")
    bbox = asset.get("bbox")
    if page is None or not bbox or len(bbox) != 4:
        return []
    return [{"page": int(page), "bbox": [float(value) for value in bbox]}]
