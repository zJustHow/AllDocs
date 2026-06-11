import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DocumentResponse
from app.db.models import Document, DocumentStatus
from app.db.session import get_db
from app.services.storage import StorageService
from app.workers.tasks import process_document

router = APIRouter(prefix="/documents", tags=["documents"])


def _inline_content_disposition(filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "ignore").decode() or "document.pdf"
    if ascii_fallback == filename:
        return f'inline; filename="{ascii_fallback}"'
    return f"inline; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


@router.post("", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    document_id = uuid.uuid4()
    object_key = f"{document_id}/{file.filename}"
    storage = StorageService()
    storage.upload(object_key, data, file.content_type or "application/pdf")

    document = Document(
        id=document_id,
        name=file.filename,
        object_key=object_key,
        status=DocumentStatus.pending,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    process_document.delay(str(document.id))
    return DocumentResponse.model_validate(document)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(db: AsyncSession = Depends(get_db)) -> list[DocumentResponse]:
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return [DocumentResponse.model_validate(item) for item in result.scalars().all()]


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = StorageService()
    data = storage.download(document.object_key)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": _inline_content_disposition(document.name)},
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    document = await db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = StorageService()
    storage.delete(document.object_key)

    from app.config import get_settings
    from app.services.fulltext_store import FulltextStore
    from app.services.vector_store import VectorStore

    VectorStore().delete_by_document(document_id)
    settings = get_settings()
    if settings.hybrid_enabled:
        FulltextStore().delete_by_document(document_id)

    await db.delete(document)
    await db.commit()
    return {"status": "deleted"}
