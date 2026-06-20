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


def embed_dedupe_key(payload: dict[str, Any]) -> str:
    content_hash = payload.get("content_hash")
    if content_hash:
        return f"hash:{content_hash}"

    asset_id = payload.get("asset_id")
    if asset_id:
        return f"asset:{asset_id}"

    url = payload.get("url")
    if url:
        return f"url:{url}"

    document_id = payload.get("document_id")
    page = payload.get("page")
    if document_id and page is not None:
        return f"page:{document_id}:{page}"
    return f"embed:{id(payload)}"


def strip_inline_markers(content: str) -> str:
    return inline_citation_marker_pattern().sub("", content).strip()
