from threading import Lock

import cv2
import fitz
import numpy as np

from app.config import Settings, get_settings
from app.services.pdf_header_footer import HeaderFooterFilter, filter_ocr_lines

_lock = Lock()
_ocr_engine = None


def _get_ocr_engine(settings: Settings):
    global _ocr_engine
    if _ocr_engine is None:
        with _lock:
            if _ocr_engine is None:
                from paddleocr import PaddleOCR

                _ocr_engine = PaddleOCR(
                    use_angle_cls=True,
                    lang=settings.ocr_lang,
                    use_gpu=False,
                    show_log=False,
                )
    return _ocr_engine


def _format_ocr_result(
    result: list | None,
    *,
    page_height: float | None = None,
    hf: HeaderFooterFilter | None = None,
) -> str:
    if not result or result[0] is None:
        return ""

    items: list[tuple[float, float, str]] = []
    for line in result[0]:
        box, (text, confidence) = line
        if confidence < 0.5 or not text.strip():
            continue
        y_center = sum(point[1] for point in box) / len(box)
        x_center = sum(point[0] for point in box) / len(box)
        items.append((y_center, x_center, text.strip()))

    if page_height is not None:
        items = filter_ocr_lines(items, page_height, hf)

    items.sort(key=lambda item: (round(item[0] / 12), item[1]))
    return "\n".join(item[2] for item in items)


class OCRService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def recognize_page(
        self,
        page: fitz.Page,
        *,
        hf: HeaderFooterFilter | None = None,
    ) -> str:
        scale = self.settings.ocr_render_scale
        matrix = fitz.Matrix(scale, scale)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        return self.recognize_bytes(
            pixmap.tobytes("png"),
            page_height=float(page.rect.height) * scale,
            hf=hf,
        )

    def recognize_bytes(
        self,
        image_bytes: bytes,
        *,
        page_height: float | None = None,
        hf: HeaderFooterFilter | None = None,
    ) -> str:
        image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return ""

        engine = _get_ocr_engine(self.settings)
        result = engine.ocr(image, cls=True)
        effective_height = page_height
        if effective_height is None and hf is not None:
            effective_height = float(image.shape[0])
        return _format_ocr_result(
            result,
            page_height=effective_height,
            hf=hf,
        )
