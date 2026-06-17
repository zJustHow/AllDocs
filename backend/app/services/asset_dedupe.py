"""Content-addressed asset IDs for per-document image deduplication."""

from __future__ import annotations

import hashlib
import uuid


def asset_content_hash(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes).hexdigest()


def stable_asset_id(document_id: uuid.UUID, png_bytes: bytes) -> uuid.UUID:
    return uuid.uuid5(document_id, asset_content_hash(png_bytes))


class AssetDedupeRegistry:
    """Map identical PNG bytes to one stable asset id and object key per document."""

    def __init__(self, document_id: uuid.UUID) -> None:
        self.document_id = document_id
        self._by_hash: dict[str, tuple[uuid.UUID, str]] = {}

    def resolve(self, png_bytes: bytes) -> tuple[uuid.UUID, str, bool]:
        """Return (asset_id, object_key, needs_upload)."""
        content_hash = asset_content_hash(png_bytes)
        cached = self._by_hash.get(content_hash)
        if cached is not None:
            asset_id, object_key = cached
            return asset_id, object_key, False

        asset_id = stable_asset_id(self.document_id, png_bytes)
        object_key = f"{self.document_id}/assets/{asset_id}.png"
        self._by_hash[content_hash] = (asset_id, object_key)
        return asset_id, object_key, True
