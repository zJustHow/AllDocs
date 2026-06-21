import asyncio
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DocumentResponse
from app.db.models import Document, DocumentStatus
from app.db.session import get_db
from app.services.document_reindex import (
    find_reindexable_by_name,
    reset_document_for_reindex,
    schedule_document_reindex,
)
from app.services.file_types import (
    get_extension,
    is_supported_filename,
    resolve_content_type,
    supported_formats_payload,
    supported_formats_label,
)
from app.services.page_render import render_page_png
from app.services.document_parsers import decode_text_bytes, render_docx_preview_html
from app.services.storage import StorageService
from app.workers.tasks import delete_document as delete_document_task, process_document
from app.workers.enqueue import enqueue

router = APIRouter(prefix="/documents", tags=["documents"])


def _inline_content_disposition(filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "ignore").decode() or "document"
    if ascii_fallback == filename:
        return f'inline; filename="{ascii_fallback}"'
    return f"inline; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


def _document_media_type(document: Document) -> str:
    if document.content_type:
        return document.content_type
    return resolve_content_type(document.name)


@router.post("", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    if not is_supported_filename(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Supported formats: {supported_formats_label()}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    content_type = resolve_content_type(file.filename, file.content_type)
    storage = StorageService()
    existing = await find_reindexable_by_name(db, file.filename)
    if existing:
        await asyncio.to_thread(storage.upload, existing.object_key, data, content_type)
        existing.content_type = content_type
        reset_document_for_reindex(existing)
        await db.commit()
        await db.refresh(existing)
        enqueue(process_document, str(existing.id))
        return DocumentResponse.model_validate(existing)

    document_id = uuid.uuid4()
    object_key = f"{document_id}/{file.filename}"
    await asyncio.to_thread(storage.upload, object_key, data, content_type)

    document = Document(
        id=document_id,
        name=file.filename,
        object_key=object_key,
        content_type=content_type,
        status=DocumentStatus.pending,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    enqueue(process_document, str(document.id))
    return DocumentResponse.model_validate(document)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(db: AsyncSession = Depends(get_db)) -> list[DocumentResponse]:
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return [DocumentResponse.model_validate(item) for item in result.scalars().all()]


@router.get("/formats")
async def get_supported_formats() -> dict:
    return supported_formats_payload()


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    document = await db.get(Document, document_id)
    if not document or document.status == DocumentStatus.deleting:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = StorageService()
    data = await asyncio.to_thread(storage.download, document.object_key)
    return Response(
        content=data,
        media_type=_document_media_type(document),
        headers={"Content-Disposition": _inline_content_disposition(document.name)},
    )


@router.get("/{document_id}/preview")
async def get_document_preview(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    document = await db.get(Document, document_id)
    if not document or document.status == DocumentStatus.deleting:
        raise HTTPException(status_code=404, detail="Document not found")

    ext = get_extension(document.name)
    if ext not in {".docx", ".html", ".htm"}:
        raise HTTPException(status_code=400, detail="Preview is not supported")

    data = await asyncio.to_thread(StorageService().download, document.object_key)
    if ext == ".docx":
        data = await asyncio.to_thread(render_docx_preview_html, data)
        data = data.encode("utf-8")
    else:
        data = decode_text_bytes(data).encode("utf-8")

    return Response(
        content=data,
        media_type="text/html; charset=utf-8",
        headers={"Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'"},
    )


@router.get("/{document_id}/pages/{page}/render")
async def render_document_page(
    document_id: uuid.UUID,
    page: int,
    scale: float = Query(default=2.0, ge=0.5, le=4.0),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be >= 1")

    document = await db.get(Document, document_id)
    if not document or document.status == DocumentStatus.deleting:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = StorageService()
    file_bytes = await asyncio.to_thread(storage.download, document.object_key)
    try:
        rendered = await asyncio.to_thread(
            render_page_png, file_bytes, document.name, page, scale=scale
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ext = get_extension(document.name)
    media_type = "image/png" if ext == ".pdf" else _document_media_type(document)
    return Response(
        content=rendered,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/{document_id}/reindex", response_model=DocumentResponse)
async def reindex_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        document = await schedule_document_reindex(db, document)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status == DocumentStatus.deleting:
        enqueue(delete_document_task, str(document_id))
        return {"status": "deleting"}

    document.progress_message = document.status.value
    document.status = DocumentStatus.deleting
    document.progress = 0
    document.error_message = None
    await db.commit()

    enqueue(delete_document_task, str(document_id))
    return {"status": "deleting"}
