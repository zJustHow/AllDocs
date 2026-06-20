"""Shared PDF table-of-contents types used by ingestion and lookup."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TocEntry:
    level: int
    title: str
    start_page: int
    end_page: int
    path: str


@dataclass(frozen=True)
class TocAnchor:
    level: int
    title: str
    path: str
    page: int
    y: float
    has_y: bool = False


def toc_entry_to_dict(entry: TocEntry) -> dict:
    return {
        "level": entry.level,
        "title": entry.title,
        "start_page": entry.start_page,
        "end_page": entry.end_page,
        "path": entry.path,
    }


def toc_entries_from_dicts(items: list[dict]) -> list[TocEntry]:
    return [
        TocEntry(
            level=int(item["level"]),
            title=str(item["title"]),
            start_page=int(item["start_page"]),
            end_page=int(item["end_page"]),
            path=str(item["path"]),
        )
        for item in items
    ]
