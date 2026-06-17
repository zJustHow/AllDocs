"""Content-addressed asset IDs for per-document image deduplication."""

from __future__ import annotations

import hashlib
import uuid

from app.services.visual_hash import (
    VISUAL_HAMMING_THRESHOLD,
    average_hash_bits,
    hamming_distance,
)


def asset_content_hash(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes).hexdigest()


def stable_asset_id(document_id: uuid.UUID, png_bytes: bytes) -> uuid.UUID:
    return uuid.uuid5(document_id, asset_content_hash(png_bytes))


class AssetDedupeRegistry:
    """Map identical or near-identical PNG bytes to one stable asset id per document."""

    def __init__(self, document_id: uuid.UUID) -> None:
        self.document_id = document_id
        self._by_hash: dict[str, tuple[uuid.UUID, str]] = {}
        self._by_phash: list[tuple[int, uuid.UUID, str]] = []

    def resolve(self, png_bytes: bytes) -> tuple[uuid.UUID, str, bool]:
        """Return (asset_id, object_key, needs_upload)."""
        content_hash = asset_content_hash(png_bytes)
        cached = self._by_hash.get(content_hash)
        if cached is not None:
            asset_id, object_key = cached
            return asset_id, object_key, False

        phash = average_hash_bits(png_bytes)
        if phash is not None:
            for existing_phash, asset_id, object_key in self._by_phash:
                if hamming_distance(phash, existing_phash) <= VISUAL_HAMMING_THRESHOLD:
                    self._by_hash[content_hash] = (asset_id, object_key)
                    return asset_id, object_key, False

        asset_id = stable_asset_id(self.document_id, png_bytes)
        object_key = f"{self.document_id}/assets/{asset_id}.png"
        self._by_hash[content_hash] = (asset_id, object_key)
        if phash is not None:
            self._by_phash.append((phash, asset_id, object_key))
        return asset_id, object_key, True


class AssetBindTracker:
    """Track visual assets so each image/table binds to at most one chunk per document."""

    def __init__(self) -> None:
        self._by_hash: set[str] = set()
        self._by_phash: list[tuple[int, str]] = []

    def claim(self, png_bytes: bytes) -> bool:
        """Return True when this PNG may be bound; False if already claimed."""
        if not png_bytes:
            return False

        content_hash = asset_content_hash(png_bytes)
        if content_hash in self._by_hash:
            return False

        phash = average_hash_bits(png_bytes)
        if phash is not None:
            for existing_phash, existing_hash in self._by_phash:
                if hamming_distance(phash, existing_phash) <= VISUAL_HAMMING_THRESHOLD:
                    self._by_hash.add(existing_hash)
                    return False
            self._by_phash.append((phash, content_hash))

        self._by_hash.add(content_hash)
        return True
