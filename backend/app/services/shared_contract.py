"""Load marker and file-format contracts shared with the frontend."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


def _shared_dir() -> Path:
    path = Path(__file__).resolve()
    for parent in path.parents:
        candidate = parent / "shared"
        if (candidate / "markers.json").exists():
            return candidate
    raise FileNotFoundError("shared/markers.json not found")


@lru_cache
def load_markers() -> dict[str, Any]:
    return json.loads((_shared_dir() / "markers.json").read_text(encoding="utf-8"))


@lru_cache
def load_file_formats() -> dict[str, Any]:
    return json.loads((_shared_dir() / "file_formats.json").read_text(encoding="utf-8"))


@lru_cache
def inline_citation_ref_pattern() -> re.Pattern[str]:
    return re.compile(load_markers()["regex"]["inlineCitationRef"])


@lru_cache
def inline_citation_marker_pattern() -> re.Pattern[str]:
    return re.compile(load_markers()["regex"]["inlineCitationMarker"])


@lru_cache
def embed_marker_pattern() -> re.Pattern[str]:
    return re.compile(load_markers()["regex"]["embedMarker"])


@lru_cache
def embed_marker_loose_pattern() -> re.Pattern[str]:
    return re.compile(load_markers()["regex"]["embedMarkerLoose"])


@lru_cache
def message_token_pattern() -> re.Pattern[str]:
    return re.compile(load_markers()["regex"]["messageToken"])


def citation_ref_pattern(ref: int) -> re.Pattern[str]:
    return re.compile(rf"\[\s*{ref}\s*\]|【\s*{ref}\s*】")


def format_embed_marker(ref: int) -> str:
    return load_markers()["embed"]["markerTemplate"].replace("{ref}", str(ref))


def normalized_bbox_key(bbox: list | tuple | None) -> str | None:
    if not bbox or len(bbox) != 4:
        return None
    decimals = int(load_markers()["embed"]["bboxRoundDecimals"])
    return ",".join(str(round(float(value), decimals)) for value in bbox)


def embed_dedupe_key(payload: dict[str, Any]) -> str:
    asset_id = payload.get("asset_id")
    if asset_id:
        return f"asset:{asset_id}"

    embed_type = payload.get("type") or "figure"
    document_id = payload.get("document_id")
    page = payload.get("page")
    bbox_key = normalized_bbox_key(payload.get("bbox"))

    if embed_type == "figure" and document_id and page is not None:
        if bbox_key:
            return f"figure:{document_id}:{page}:{bbox_key}"
        return f"figure:{document_id}:{page}"

    if embed_type == "table" and document_id and page is not None and bbox_key:
        return f"table:{document_id}:{page}:{bbox_key}"

    url = payload.get("url")
    if url:
        return f"url:{url}"

    if document_id and page is not None:
        return f"page:{document_id}:{page}"
    return f"embed:{id(payload)}"


def strip_inline_markers(content: str) -> str:
    text = inline_citation_marker_pattern().sub("", content)
    text = embed_marker_loose_pattern().sub("", text)
    return text.strip()
