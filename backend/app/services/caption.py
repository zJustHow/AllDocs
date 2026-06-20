"""VLM caption generation during document ingestion."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass

from openai import OpenAI

from app.config import Settings, get_settings
from app.services.caption_api import caption_api_base_url, caption_api_key, caption_model_name

logger = logging.getLogger(__name__)

CLASSIFY_SYSTEM_PROMPT = (
    "你是产品操作指南视觉资产分析助手。根据图片判断类型并写出便于检索的中文描述。"
    "只输出 JSON，格式："
    '{"kind":"table|figure|diagram|photo","caption":"1-3句描述，提取关键参数与标签，不得编造"}。'
    "kind 说明：table=数据或规格表格；figure/diagram=示意图接线图流程图；photo=照片或界面截图。"
)

_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


@dataclass(frozen=True)
class AssetVisionResult:
    kind: str
    caption: str


def _parse_vision_json(raw: str) -> AssetVisionResult | None:
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(text)
        if match is None:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    if not isinstance(payload, dict):
        return None
    kind = str(payload.get("kind") or "figure").strip().lower()
    caption = str(payload.get("caption") or "").strip()
    if kind == "table":
        normalized_kind = "table"
    elif kind in {"diagram", "wiring", "schematic"}:
        normalized_kind = "diagram"
    elif kind == "photo":
        normalized_kind = "photo"
    else:
        normalized_kind = "figure"
    if not caption:
        return None
    return AssetVisionResult(kind=normalized_kind, caption=caption)


class CaptionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = OpenAI(
            base_url=caption_api_base_url(self.settings),
            api_key=caption_api_key(self.settings),
        )

    def _model(self) -> str:
        return caption_model_name(self.settings)

    def classify_and_describe(
        self,
        image_bytes: bytes,
        media_type: str = "image/png",
    ) -> AssetVisionResult | None:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        try:
            response = self.client.chat.completions.create(
                model=self._model(),
                messages=[
                    {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "分析这张手册插图，输出 JSON（kind + caption）。",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                            },
                        ],
                    },
                ],
                temperature=0.1,
            )
        except Exception:
            logger.warning("VLM classify request failed", exc_info=True)
            return None

        content = response.choices[0].message.content or ""
        return _parse_vision_json(content)
