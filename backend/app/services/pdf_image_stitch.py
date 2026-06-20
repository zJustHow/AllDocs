"""Vertically stitch rendered PNG crops (e.g. cross-page table fragments)."""

from __future__ import annotations

import fitz


def stitch_png_bytes_vertically(
    images: list[bytes],
    *,
    gap: int = 2,
) -> tuple[bytes, int, int]:
    """Stack PNG images top-to-bottom on a white canvas."""
    if not images:
        raise ValueError("at least one image is required")
    if len(images) == 1:
        pixmap = fitz.Pixmap(images[0])
        return images[0], pixmap.width, pixmap.height

    sizes: list[tuple[int, int]] = []
    for data in images:
        pixmap = fitz.Pixmap(data)
        sizes.append((pixmap.width, pixmap.height))

    gap_px = max(0, int(gap))
    width = max(item[0] for item in sizes)
    height = sum(item[1] for item in sizes) + gap_px * (len(sizes) - 1)

    document = fitz.open()
    try:
        page = document.new_page(width=width, height=height)
        page.draw_rect(page.rect, color=(1, 1, 1), fill=(1, 1, 1))

        y_offset = 0.0
        for data, (segment_width, segment_height) in zip(images, sizes, strict=True):
            rect = fitz.Rect(0, y_offset, segment_width, y_offset + segment_height)
            page.insert_image(rect, stream=data)
            y_offset += segment_height + gap_px

        rendered = page.get_pixmap(alpha=False)
        return rendered.tobytes("png"), rendered.width, rendered.height
    finally:
        document.close()
