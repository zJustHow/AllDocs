"""SQLite helpers for in-memory ORM tests."""

from __future__ import annotations

from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB


def create_sqlite_schema(bind, metadata: MetaData) -> None:
    """Create ORM tables on SQLite by substituting PostgreSQL-only column types."""
    swaps: list[tuple[object, object]] = []
    for table in metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                swaps.append((column, column.type))
                column.type = JSON()
    try:
        metadata.create_all(bind)
    finally:
        for column, original in swaps:
            column.type = original
