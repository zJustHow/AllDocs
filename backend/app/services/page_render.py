"""Render document pages or image files to PNG bytes."""

from __future__ import annotations

import fitz

from app.services.file_types import get_extension

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def render_page_png(
    file_bytes: bytes,
    filename: str,
    page: int,
    *,
    scale: float = 2.0,
    bbox: tuple[float, float, float, float] | None = None,
) -> bytes:
    ext = get_extension(filename)
    if ext == ".pdf":
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        try:
            if page < 1 or page > doc.page_count:
                raise ValueError(f"Page {page} out of range (1-{doc.page_count})")
            pdf_page = doc[page - 1]
            matrix = fitz.Matrix(scale, scale)
            clip = fitz.Rect(bbox) if bbox else None
            pixmap = pdf_page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
            return pixmap.tobytes("png")
        finally:
            doc.close()

    if ext in _IMAGE_EXTENSIONS:
        if page != 1:
            raise ValueError("Image documents only have page 1")
        return file_bytes

    raise ValueError(f"Page rendering is not supported for {filename}")
