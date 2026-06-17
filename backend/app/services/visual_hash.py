"""Perceptual hashing for near-duplicate image detection."""

from __future__ import annotations

import cv2
import numpy as np

VISUAL_HAMMING_THRESHOLD = 5
_AHASH_SIZE = 8


def average_hash_bits(png_bytes: bytes) -> int | None:
    """Return a 64-bit average hash for PNG bytes, or None if decode fails."""
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None

    resized = cv2.resize(
        img,
        (_AHASH_SIZE, _AHASH_SIZE),
        interpolation=cv2.INTER_AREA,
    )
    mean = float(resized.mean())
    bits = (resized >= mean).flatten()
    value = 0
    for index, bit in enumerate(bits):
        if bit:
            value |= 1 << index
    return value


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()
