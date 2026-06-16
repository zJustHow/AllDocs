"""Chunk visual asset URL helpers."""

from __future__ import annotations

from uuid import UUID


def asset_url(asset_id: UUID | str) -> str:
    return f"/api/v1/assets/{asset_id}"
