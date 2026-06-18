"""Match in-text figure/table references to numbered visual assets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.services.pdf_captions import normalize_figure_number
from app.services.pdf_embedded_images import (
    EmbeddedFigure,
    ParsedAttachedAsset,
    _figure_to_attached_asset,
)
from app.services.pdf_tables import EmbeddedTable, _table_to_attached_asset

_NUMBER = r"(?P<chapter>\d+)\s*[-–—]\s*(?P<num>\d+)"
_FIGURE_REF_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"(?:如图|参考图|见图|参见图)\s*{_NUMBER}"),
    re.compile(rf"图\s*{_NUMBER}\s*所示"),
    re.compile(rf"图\s*{_NUMBER}(?!\s*[-–—]\s*\d)"),
)
_TABLE_REF_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"(?:见表|参考表|参见表)\s*{_NUMBER}"),
    re.compile(rf"表\s*{_NUMBER}\s*所示"),
    re.compile(rf"表\s*{_NUMBER}(?!\s*[-–—]\s*\d)"),
)

AssetKind = Literal["figure", "table"]
NumberedAsset = EmbeddedFigure | EmbeddedTable


@dataclass(frozen=True)
class FigureRef:
    kind: AssetKind
    figure_number: str


def _refs_from_patterns(
    text: str,
    patterns: tuple[re.Pattern[str], ...],
    kind: AssetKind,
    seen: set[tuple[AssetKind, str]],
) -> list[FigureRef]:
    refs: list[FigureRef] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            number = normalize_figure_number(match.group("chapter"), match.group("num"))
            key = (kind, number)
            if key in seen:
                continue
            seen.add(key)
            refs.append(FigureRef(kind=kind, figure_number=number))
    return refs


def extract_figure_refs(text: str) -> list[FigureRef]:
    seen: set[tuple[AssetKind, str]] = set()
    refs = _refs_from_patterns(text, _FIGURE_REF_PATTERNS, "figure", seen)
    refs.extend(_refs_from_patterns(text, _TABLE_REF_PATTERNS, "table", seen))
    return refs


def _reverse_mention_patterns(kind: AssetKind, figure_number: str) -> tuple[re.Pattern[str], ...]:
    chapter, num = figure_number.split("-", 1)
    if kind == "figure":
        return (
            re.compile(rf"(?:如图|参考图|见图|参见图)\s*{chapter}\s*[-–—]\s*{num}"),
            re.compile(rf"图\s*{chapter}\s*[-–—]\s*{num}\s*所示"),
            re.compile(rf"图\s*{chapter}\s*[-–—]\s*{num}(?!\s*[-–—]\s*\d)"),
        )
    return (
        re.compile(rf"(?:见表|参考表|参见表)\s*{chapter}\s*[-–—]\s*{num}"),
        re.compile(rf"表\s*{chapter}\s*[-–—]\s*{num}\s*所示"),
        re.compile(rf"表\s*{chapter}\s*[-–—]\s*{num}(?!\s*[-–—]\s*\d)"),
    )


def text_mentions_figure_number(text: str, kind: AssetKind, figure_number: str) -> bool:
    return any(
        pattern.search(text) for pattern in _reverse_mention_patterns(kind, figure_number)
    )


def _asset_identity(asset: NumberedAsset) -> tuple[int, tuple[float, float, float, float]]:
    return (asset.page, asset.bbox)


def _build_numbered_asset_index(
    figures: list[EmbeddedFigure],
    tables: list[EmbeddedTable],
) -> dict[tuple[AssetKind, str], NumberedAsset]:
    index: dict[tuple[AssetKind, str], NumberedAsset] = {}
    for figure in figures:
        if not figure.figure_number:
            continue
        key = ("figure", figure.figure_number)
        index.setdefault(key, figure)
    for table in tables:
        if not table.figure_number:
            continue
        key = ("table", table.figure_number)
        index.setdefault(key, table)
    return index


def _chunk_has_numbered_asset(
    chunk: object,
    *,
    kind: AssetKind,
    figure_number: str,
) -> bool:
    for attached in getattr(chunk, "attached_assets", []) or []:
        if attached.asset_type == kind and attached.figure_number == figure_number:
            return True
    return False


def _text_chunks(chunks: list) -> list:
    candidates = [
        chunk
        for chunk in chunks
        if getattr(chunk, "text", "").strip()
    ]
    candidates.sort(key=lambda chunk: int(getattr(chunk, "chunk_index", 0)))
    return candidates


def _to_attached_asset(ref: FigureRef, asset: NumberedAsset) -> ParsedAttachedAsset:
    if ref.kind == "figure":
        return _figure_to_attached_asset(asset)
    return _table_to_attached_asset(asset)


def _try_attach(
    chunk: object,
    ref: FigureRef,
    asset: NumberedAsset,
    *,
    claimed_identities: set[tuple[int, tuple[float, float, float, float]]],
    claimed_numbers: set[tuple[AssetKind, str]],
) -> bool:
    number_key = (ref.kind, ref.figure_number)
    if number_key in claimed_numbers:
        return False
    identity = _asset_identity(asset)
    if identity in claimed_identities:
        return False
    if _chunk_has_numbered_asset(chunk, kind=ref.kind, figure_number=ref.figure_number):
        claimed_numbers.add(number_key)
        claimed_identities.add(identity)
        return False

    chunk.attached_assets.append(_to_attached_asset(ref, asset))
    claimed_numbers.add(number_key)
    claimed_identities.add(identity)
    return True


def _attach_by_forward_refs(
    chunks: list,
    index: dict[tuple[AssetKind, str], NumberedAsset],
    *,
    claimed_identities: set[tuple[int, tuple[float, float, float, float]]],
    claimed_numbers: set[tuple[AssetKind, str]],
) -> None:
    for chunk in _text_chunks(chunks):
        for ref in extract_figure_refs(chunk.text):
            asset = index.get((ref.kind, ref.figure_number))
            if asset is None:
                continue
            _try_attach(
                chunk,
                ref,
                asset,
                claimed_identities=claimed_identities,
                claimed_numbers=claimed_numbers,
            )


def _attach_by_reverse_index(
    chunks: list,
    index: dict[tuple[AssetKind, str], NumberedAsset],
    *,
    claimed_identities: set[tuple[int, tuple[float, float, float, float]]],
    claimed_numbers: set[tuple[AssetKind, str]],
) -> None:
    """Match caption figure_number to chunks that mention the same number in body text."""
    for (kind, figure_number), asset in index.items():
        if (kind, figure_number) in claimed_numbers:
            continue
        if _asset_identity(asset) in claimed_identities:
            continue

        ref = FigureRef(kind=kind, figure_number=figure_number)
        for chunk in _text_chunks(chunks):
            if not text_mentions_figure_number(chunk.text, kind, figure_number):
                continue
            if _try_attach(
                chunk,
                ref,
                asset,
                claimed_identities=claimed_identities,
                claimed_numbers=claimed_numbers,
            ):
                break


def attach_by_explicit_refs(
    chunks: list,
    figures: list[EmbeddedFigure],
    tables: list[EmbeddedTable],
) -> tuple[list[EmbeddedFigure], list[EmbeddedTable]]:
    """Attach assets by forward refs and caption reverse index; return unclaimed assets."""
    index = _build_numbered_asset_index(figures, tables)
    if not index:
        return figures, tables

    claimed_identities: set[tuple[int, tuple[float, float, float, float]]] = set()
    claimed_numbers: set[tuple[AssetKind, str]] = set()

    _attach_by_forward_refs(
        chunks,
        index,
        claimed_identities=claimed_identities,
        claimed_numbers=claimed_numbers,
    )
    _attach_by_reverse_index(
        chunks,
        index,
        claimed_identities=claimed_identities,
        claimed_numbers=claimed_numbers,
    )

    orphan_figures = [
        figure for figure in figures if _asset_identity(figure) not in claimed_identities
    ]
    orphan_tables = [
        table for table in tables if _asset_identity(table) not in claimed_identities
    ]
    return orphan_figures, orphan_tables
