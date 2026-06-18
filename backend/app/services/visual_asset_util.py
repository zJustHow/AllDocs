"""Shared helpers for table/figure assets on chunks."""

from __future__ import annotations

VISUAL_ASSET_TYPES = frozenset({"table", "figure"})


def chunk_visual_assets(chunk: dict) -> list[dict]:
    assets: list[dict] = []
    for asset in chunk.get("assets") or []:
        if not asset.get("asset_id"):
            continue
        asset_type = asset.get("type") or "figure"
        if asset_type in VISUAL_ASSET_TYPES:
            assets.append(asset)
    return assets
