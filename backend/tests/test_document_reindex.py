from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import DocumentStatus
from app.services.document_reindex import reset_document_for_reindex, schedule_document_reindex


def _document(**overrides: object) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "status": DocumentStatus.ready,
        "error_message": "old error",
        "progress": 100,
        "progress_message": "done",
        "page_count": 12,
        "ocr_pages": 3,
        "toc_entries": [{"title": "Intro"}],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_reset_document_for_reindex_clears_progress_fields() -> None:
    document = _document()
    reset_document_for_reindex(document)

    assert document.status == DocumentStatus.pending
    assert document.error_message is None
    assert document.progress == 0
    assert document.progress_message == "等待重索引"
    assert document.page_count is None
    assert document.ocr_pages == 0
    assert document.toc_entries is None


def test_schedule_document_reindex_rejects_deleting_documents() -> None:
    document = _document(status=DocumentStatus.deleting)
    db = AsyncMock()

    with pytest.raises(ValueError, match="being deleted"):
        asyncio.run(schedule_document_reindex(db, document))


def test_schedule_document_reindex_requeues_pending_documents() -> None:
    document = _document(status=DocumentStatus.pending)
    db = AsyncMock()

    with patch("app.services.document_reindex.enqueue") as enqueue:
        result = asyncio.run(schedule_document_reindex(db, document))

    assert result is document
    enqueue.assert_called_once()
    db.commit.assert_not_called()


def test_schedule_document_reindex_resets_ready_documents() -> None:
    document = _document(status=DocumentStatus.ready)
    db = AsyncMock()
    db.refresh = AsyncMock()

    with patch("app.services.document_reindex.enqueue") as enqueue:
        result = asyncio.run(schedule_document_reindex(db, document))

    assert result.status == DocumentStatus.pending
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(document)
    enqueue.assert_called_once()
