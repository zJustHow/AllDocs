"""Build per-chunk sub indexes mapping cited sentences to visual assets."""

from __future__ import annotations

import re
from typing import Any, Protocol

from app.services.pdf_refs import FigureRef, extract_figure_refs
from app.services.visual_asset_util import VISUAL_ASSET_TYPES

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*")
_MIN_POSITION = (0, float("-inf"))
_MAX_POSITION = (10**9, float("inf"))


class _AssetLike(Protocol):
    id: Any
    asset_type: str
    figure_number: str | None
    figure_caption: str | None
    caption: str | None
    page: int | None
    bbox: list[float] | None


def split_sentences(text: str) -> list[str]:
    """Split chunk text into non-empty sentences."""
    text = text.strip()
    if not text:
        return []

    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]
    return sentences if sentences else [text]


def split_chunk_into_subs(text: str) -> list[str]:
    """One sub per sentence that cites a figure/table; each sub is that sentence only."""
    return [sentence for sentence in split_sentences(text) if extract_figure_refs(sentence)]


def _asset_dict(asset: _AssetLike | dict[str, Any]) -> dict[str, Any]:
    if isinstance(asset, dict):
        return asset
    return {
        "asset_id": str(asset.id),
        "type": asset.asset_type,
        "figure_number": asset.figure_number,
        "figure_caption": asset.figure_caption,
        "caption": asset.caption,
        "page": asset.page,
        "bbox": asset.bbox,
    }


def _asset_key(asset_type: str, figure_number: str) -> tuple[str, str]:
    return (asset_type, figure_number)


def _assets_by_number(assets: list[_AssetLike | dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in assets:
        item = _asset_dict(raw)
        asset_type = item.get("type") or "figure"
        figure_number = item.get("figure_number")
        if not figure_number or asset_type not in VISUAL_ASSET_TYPES:
            continue
        index.setdefault(_asset_key(asset_type, figure_number), item)
    return index


def _assets_by_id(assets: list[_AssetLike | dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for raw in assets:
        item = _asset_dict(raw)
        asset_id = str(item.get("asset_id") or "")
        if asset_id:
            by_id[asset_id] = item
    return by_id


def _assets_for_refs(
    refs: list[FigureRef],
    assets_index: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for ref in refs:
        asset = assets_index.get((ref.kind, ref.figure_number))
        if asset is None:
            continue
        asset_id = str(asset.get("asset_id") or "")
        if asset_id and asset_id in seen_ids:
            continue
        if asset_id:
            seen_ids.add(asset_id)
        matched.append(asset)
    return matched


def _append_index_text(base: str, asset: dict[str, Any]) -> str:
    parts = [base.strip()] if base.strip() else []
    for field in ("figure_caption", "caption"):
        value = str(asset.get(field) or "").strip()
        if value and value not in base:
            parts.append(value)
    return "\n".join(parts)


def _asset_position(asset: dict[str, Any]) -> tuple[int, float]:
    page = int(asset.get("page") or 0)
    bbox = asset.get("bbox")
    y = float(bbox[1]) if isinstance(bbox, list) and len(bbox) >= 2 else 0.0
    return (page, y)


def _bound_after(assets: list[dict[str, Any]]) -> tuple[int, float]:
    if not assets:
        return _MIN_POSITION
    return max(_asset_position(asset) for asset in assets)


def _bound_before(assets: list[dict[str, Any]]) -> tuple[int, float]:
    if not assets:
        return _MAX_POSITION
    return min(_asset_position(asset) for asset in assets)


def _position_in_open_interval(
    position: tuple[int, float],
    lower: tuple[int, float],
    upper: tuple[int, float],
) -> bool:
    return lower < position < upper


def _resolve_sub_assets(sub: dict[str, Any], assets_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for asset_id in sub.get("asset_ids") or []:
        asset = assets_by_id.get(str(asset_id))
        if asset is not None:
            resolved.append(asset)
    return resolved


def _position_distance(
    left: tuple[int, float],
    right: tuple[int, float],
) -> tuple[int, float]:
    return (abs(left[0] - right[0]), abs(left[1] - right[1]))


def _pick_nearest_ref_sub(
    asset: dict[str, Any],
    *,
    prev_sub: dict[str, Any] | None,
    next_sub: dict[str, Any] | None,
    assets_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if prev_sub is None:
        return next_sub
    if next_sub is None:
        return prev_sub

    position = _asset_position(asset)
    prev_anchor = _bound_after(_resolve_sub_assets(prev_sub, assets_by_id))
    next_anchor = _bound_before(_resolve_sub_assets(next_sub, assets_by_id))
    dist_prev = _position_distance(position, prev_anchor)
    dist_next = _position_distance(position, next_anchor)
    return prev_sub if dist_prev <= dist_next else next_sub


def _merge_assets_into_sub(sub: dict[str, Any], assets: list[dict[str, Any]]) -> None:
    asset_ids = list(sub.get("asset_ids") or [])
    index_text = str(sub.get("index_text") or sub.get("text") or "")
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id and asset_id not in asset_ids:
            asset_ids.append(asset_id)
        index_text = _append_index_text(index_text, asset)
    sub["asset_ids"] = asset_ids
    sub["index_text"] = index_text


def _build_ref_sub(
    sub_text: str,
    refs: list[FigureRef],
    assets_index: dict[tuple[str, str], dict[str, Any]],
    matched_asset_ids: set[str],
) -> dict[str, Any]:
    figure_numbers = [ref.figure_number for ref in refs if ref.kind == "figure"]
    table_numbers = [ref.figure_number for ref in refs if ref.kind == "table"]
    sub_assets = _assets_for_refs(refs, assets_index)

    index_text = sub_text
    asset_ids: list[str] = []
    for asset in sub_assets:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id:
            asset_ids.append(asset_id)
            matched_asset_ids.add(asset_id)
        index_text = _append_index_text(index_text, asset)

    return {
        "kind": "ref",
        "text": sub_text,
        "index_text": index_text,
        "figure_numbers": figure_numbers,
        "table_numbers": table_numbers,
        "asset_ids": asset_ids,
    }


def _build_gap_sub(gap_text: str, assets: list[dict[str, Any]]) -> dict[str, Any]:
    index_text = gap_text
    asset_ids: list[str] = []
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id:
            asset_ids.append(asset_id)
        index_text = _append_index_text(index_text, asset)
    return {
        "kind": "gap",
        "text": gap_text,
        "index_text": index_text,
        "figure_numbers": [],
        "table_numbers": [],
        "asset_ids": asset_ids,
    }


def _collect_unmatched(
    assets: list[_AssetLike | dict[str, Any]],
    matched_asset_ids: set[str],
) -> list[dict[str, Any]]:
    unmatched: list[dict[str, Any]] = []
    for raw in assets:
        item = _asset_dict(raw)
        asset_id = str(item.get("asset_id") or "")
        asset_type = item.get("type") or "figure"
        if not asset_id or asset_id in matched_asset_ids:
            continue
        if asset_type not in VISUAL_ASSET_TYPES:
            continue
        unmatched.append(item)
    return unmatched


def _subs_for_unmatched_only(unmatched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not unmatched:
        return []

    index_text = ""
    asset_ids: list[str] = []
    for asset in unmatched:
        asset_id = str(asset.get("asset_id") or "")
        if asset_id:
            asset_ids.append(asset_id)
        index_text = _append_index_text(index_text, asset)
    return [
        {
            "sub_index": 0,
            "kind": "gap",
            "text": "",
            "index_text": index_text,
            "figure_numbers": [],
            "table_numbers": [],
            "asset_ids": asset_ids,
        }
    ]


def _renumber_subs(subs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, sub in enumerate(subs):
        sub["sub_index"] = index
    return subs


def _process_gap(
    *,
    gap_sentences: list[str],
    anchor_assets: list[dict[str, Any]] | None,
    next_assets: list[dict[str, Any]] | None,
    prev_sub: dict[str, Any] | None,
    next_sub: dict[str, Any] | None,
    unmatched: list[dict[str, Any]],
    assigned: set[str],
    assets_by_id: dict[str, dict[str, Any]],
    final_subs: list[dict[str, Any]],
) -> None:
    lower = _bound_after(anchor_assets or [])
    if anchor_assets is None:
        lower = _MIN_POSITION
    upper = _bound_before(next_assets or [])
    if next_assets is None:
        upper = _MAX_POSITION

    gap_candidates: list[dict[str, Any]] = []
    for asset in unmatched:
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id or asset_id in assigned:
            continue
        if _position_in_open_interval(_asset_position(asset), lower, upper):
            gap_candidates.append(asset)

    if not gap_candidates:
        return

    gap_text = "".join(gap_sentences).strip()
    if gap_text:
        final_subs.append(_build_gap_sub(gap_text, gap_candidates))
        assigned.update(str(asset.get("asset_id") or "") for asset in gap_candidates)
        return

    for asset in gap_candidates:
        target = _pick_nearest_ref_sub(
            asset,
            prev_sub=prev_sub,
            next_sub=next_sub,
            assets_by_id=assets_by_id,
        )
        if target is None:
            continue
        _merge_assets_into_sub(target, [asset])
        asset_id = str(asset.get("asset_id") or "")
        if asset_id:
            assigned.add(asset_id)


def _assign_remaining_unmatched(
    unmatched: list[dict[str, Any]],
    assigned: set[str],
    ref_subs: list[dict[str, Any]],
    assets_by_id: dict[str, dict[str, Any]],
) -> None:
    for asset in unmatched:
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id or asset_id in assigned:
            continue
        if not ref_subs:
            continue
        nearest = min(
            ref_subs,
            key=lambda sub: _position_distance(
                _asset_position(asset),
                _bound_after(_resolve_sub_assets(sub, assets_by_id)),
            ),
        )
        _merge_assets_into_sub(nearest, [asset])
        assigned.add(asset_id)


def build_chunk_sub_index(
    text: str,
    assets: list[_AssetLike | dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return ordered subs with index_text and linked asset ids for alignment."""
    assets = assets or []
    assets_index = _assets_by_number(assets)
    assets_by_id = _assets_by_id(assets)
    sentences = split_sentences(text)
    matched_asset_ids: set[str] = set()

    ref_data: list[tuple[int, dict[str, Any]]] = []
    for sentence_index, sentence in enumerate(sentences):
        refs = extract_figure_refs(sentence)
        if not refs:
            continue
        ref_data.append(
            (
                sentence_index,
                _build_ref_sub(sentence, refs, assets_index, matched_asset_ids),
            )
        )

    unmatched = _collect_unmatched(assets, matched_asset_ids)
    if not ref_data:
        return _subs_for_unmatched_only(unmatched)

    if not unmatched:
        return _renumber_subs([sub for _, sub in ref_data])

    assigned: set[str] = set()
    final_subs: list[dict[str, Any]] = []
    ref_subs = [sub for _, sub in ref_data]

    first_index, first_sub = ref_data[0]
    _process_gap(
        gap_sentences=sentences[:first_index],
        anchor_assets=None,
        next_assets=_resolve_sub_assets(first_sub, assets_by_id),
        prev_sub=None,
        next_sub=first_sub,
        unmatched=unmatched,
        assigned=assigned,
        assets_by_id=assets_by_id,
        final_subs=final_subs,
    )
    final_subs.append(first_sub)

    for current in range(len(ref_data) - 1):
        current_index, current_sub = ref_data[current]
        next_index, next_sub = ref_data[current + 1]
        _process_gap(
            gap_sentences=sentences[current_index + 1 : next_index],
            anchor_assets=_resolve_sub_assets(current_sub, assets_by_id),
            next_assets=_resolve_sub_assets(next_sub, assets_by_id),
            prev_sub=current_sub,
            next_sub=next_sub,
            unmatched=unmatched,
            assigned=assigned,
            assets_by_id=assets_by_id,
            final_subs=final_subs,
        )
        final_subs.append(next_sub)

    last_index, last_sub = ref_data[-1]
    _process_gap(
        gap_sentences=sentences[last_index + 1 :],
        anchor_assets=_resolve_sub_assets(last_sub, assets_by_id),
        next_assets=None,
        prev_sub=last_sub,
        next_sub=None,
        unmatched=unmatched,
        assigned=assigned,
        assets_by_id=assets_by_id,
        final_subs=final_subs,
    )

    _assign_remaining_unmatched(unmatched, assigned, ref_subs, assets_by_id)
    return _renumber_subs(final_subs)
