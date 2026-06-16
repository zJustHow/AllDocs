"""VLM caption generation during document ingestion."""

from __future__ import annotations

import base64
import logging

from openai import OpenAI

from app.config import Settings, get_settings
from app.services.vision_api import caption_api_base_url, caption_api_key, caption_model_name

logger = logging.getLogger(__name__)

CAPTION_SYSTEM_PROMPT = (
    "你是产品说明书图像描述助手。根据图片写出便于检索的简短描述。"
    "要求：1-3句中文；说明图表类型（如规格表、接线图、示意图、故障灯）；"
    "提取关键参数、标签、颜色与连接关系；不得编造图中没有的内容。"
    "只输出描述正文，不要标题或列表符号。"
)


class CaptionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = OpenAI(
            base_url=caption_api_base_url(self.settings),
            api_key=caption_api_key(self.settings),
        )

    def _model(self) -> str:
        return caption_model_name(self.settings)

    def caption_image(self, image_bytes: bytes, media_type: str = "image/png") -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = self.client.chat.completions.create(
            model=self._model(),
            messages=[
                {"role": "system", "content": CAPTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请描述这张说明书图片，便于用户检索「规格表」「接线图」「故障灯」等内容。",
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
        content = response.choices[0].message.content or ""
        return content.strip()
