import uuid
from unittest.mock import MagicMock

from app.db.models import Chunk, DocumentStatus
from app.workers.tasks import (
    _abort_if_deleting,
    _asset_content_hash,
    _collect_pending_asset_uploads,
    _set_progress,
    _throttled_page_progress,
)


def test_asset_content_hash_is_stable_sha256() -> None:
    digest = _asset_content_hash(b"png-bytes")
    assert len(digest) == 64
    assert _asset_content_hash(b"png-bytes") == digest


def test_collect_pending_asset_uploads_builds_asset_jobs() -> None:
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    chunk = Chunk(
        id=chunk_id,
        document_id=doc_id,
        text="正文",
        chunk_index=0,
        page=1,
        section="Intro",
    )
    attached = MagicMock()
    attached.png_bytes = b"fake-png"
    attached.asset_type = "figure"
    attached.page = 2
    attached.bbox = [0.0, 0.0, 100.0, 80.0]
    attached.width = 100
    attached.height = 80
    attached.text_summary = "图注"
    attached.figure_caption = "图1-1"
    attached.figure_number = "1-1"
    attached.vlm_caption = None
    attached.layout_regions = [{"page": 2, "bbox": [0.0, 0.0, 1.0, 1.0]}]

    parsed = MagicMock()
    parsed.attached_assets = [attached]

    pending = _collect_pending_asset_uploads(doc_id, [parsed], [chunk])

    assert len(pending) == 1
    assert pending[0].chunk_id == chunk_id
    assert pending[0].asset_type == "figure"
    assert pending[0].figure_number == "1-1"
    assert pending[0].object_key.endswith(".png")


def test_set_progress_clamps_percent() -> None:
    document = MagicMock()
    document.progress = 0
    db = MagicMock()

    _set_progress(db, document, 150, "完成", commit=False)

    assert document.progress == 100
    assert document.progress_message == "完成"
    db.commit.assert_not_called()


def test_abort_if_deleting_reflects_document_status() -> None:
    document = MagicMock()
    document.status = DocumentStatus.deleting
    db = MagicMock()

    assert _abort_if_deleting(db, document) is True
    db.refresh.assert_called_once_with(document)


def test_throttled_page_progress_commits_on_interval() -> None:
    db = MagicMock()
    document = MagicMock()
    document.progress = 0
    on_progress = _throttled_page_progress(db, document, interval=2)

    on_progress(1, 10)
    db.commit.assert_not_called()
    on_progress(2, 10)
    db.commit.assert_called_once()
    on_progress(10, 10)
    assert db.commit.call_count == 2
