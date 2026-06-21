import asyncio
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.api.documents import (
    _inline_content_disposition,
    delete_document,
    get_document_preview,
    render_document_page,
    upload_document,
)
from app.db.models import DocumentStatus


def test_content_disposition_supports_ascii_and_unicode_names() -> None:
    assert _inline_content_disposition("manual.pdf") == 'inline; filename="manual.pdf"'

    header = _inline_content_disposition("操作手册.pdf")
    assert 'filename=".pdf"' in header
    assert "filename*=UTF-8''%E6%93%8D%E4%BD%9C%E6%89%8B%E5%86%8C.pdf" in header


@pytest.mark.parametrize(
    ("filename", "content", "detail"),
    [
        ("manual.exe", b"payload", "Unsupported file type"),
        ("manual.pdf", b"", "Empty file"),
    ],
)
def test_upload_rejects_invalid_files_before_storage(
    filename: str, content: bytes, detail: str
) -> None:
    file = UploadFile(filename=filename, file=BytesIO(content))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(upload_document(file=file, db=AsyncMock()))

    assert exc_info.value.status_code == 400
    assert detail in str(exc_info.value.detail)


def test_preview_rejects_unsupported_document_types() -> None:
    document = SimpleNamespace(
        status=DocumentStatus.ready,
        name="manual.txt",
        object_key="docs/manual.txt",
    )
    db = AsyncMock()
    db.get.return_value = document

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_document_preview(uuid.uuid4(), db))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Preview is not supported"


def test_page_render_converts_renderer_errors_to_bad_request() -> None:
    document = SimpleNamespace(
        status=DocumentStatus.ready,
        name="manual.pdf",
        object_key="docs/manual.pdf",
    )
    db = AsyncMock()
    db.get.return_value = document

    with (
        patch("app.api.documents.StorageService") as storage_cls,
        patch(
            "app.api.documents.render_page_png",
            side_effect=ValueError("Page 9 is out of range"),
        ),
    ):
        storage_cls.return_value.download.return_value = b"pdf"
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(render_document_page(uuid.uuid4(), 9, 2.0, db))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Page 9 is out of range"


def test_delete_marks_document_deleting_before_enqueue() -> None:
    document_id = uuid.uuid4()
    document = SimpleNamespace(
        status=DocumentStatus.ready,
        progress_message=None,
        progress=100,
        error_message="old error",
    )
    db = AsyncMock()
    db.get.return_value = document

    with patch("app.api.documents.enqueue") as enqueue:
        result = asyncio.run(delete_document(document_id, db))

    assert result == {"status": "deleting"}
    assert document.status == DocumentStatus.deleting
    assert document.progress_message == "ready"
    assert document.progress == 0
    assert document.error_message is None
    db.commit.assert_awaited_once()
    enqueue.assert_called_once()


def test_delete_is_idempotent_while_deletion_is_in_progress() -> None:
    document_id = uuid.uuid4()
    document = SimpleNamespace(status=DocumentStatus.deleting)
    db = AsyncMock()
    db.get.return_value = document

    with patch("app.api.documents.enqueue") as enqueue:
        result = asyncio.run(delete_document(document_id, db))

    assert result == {"status": "deleting"}
    db.commit.assert_not_awaited()
    enqueue.assert_called_once()
