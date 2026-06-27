from __future__ import annotations

from app.services.shared_contract import (
    embed_dedupe_key,
    inline_citation_marker_pattern,
    inline_citation_ref_pattern,
    load_file_formats,
    load_markers,
    strip_inline_markers,
)


def test_load_markers_and_file_formats() -> None:
    markers = load_markers()
    formats = load_file_formats()

    assert "regex" in markers
    assert "types" in formats
    assert inline_citation_ref_pattern().search("[1]")
    assert inline_citation_marker_pattern().pattern


def test_embed_dedupe_key_prefers_content_hash() -> None:
    payload = {"content_hash": "abc123", "asset_id": "asset-1", "url": "/x.png"}
    assert embed_dedupe_key(payload) == "hash:abc123"


def test_embed_dedupe_key_falls_back_to_asset_page_and_object_id() -> None:
    assert embed_dedupe_key({"asset_id": "asset-1"}) == "asset:asset-1"
    assert embed_dedupe_key({"url": "/x.png"}) == "url:/x.png"
    assert embed_dedupe_key({"document_id": "doc-1", "page": 2}) == "page:doc-1:2"

    fallback_key = embed_dedupe_key({})
    assert fallback_key.startswith("embed:")


def test_strip_inline_markers_removes_citation_markers() -> None:
    text = "See step [1] and figure [2]."
    stripped = strip_inline_markers(text)
    assert "[1]" not in stripped
    assert "[2]" not in stripped
    assert "See step" in stripped
