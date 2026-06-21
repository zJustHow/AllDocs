from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentStatus
from app.workers.tasks import process_document
from app.workers.enqueue import enqueue

REINDEXABLE_STATUSES = {DocumentStatus.ready, DocumentStatus.failed}


def reset_document_for_reindex(document: Document) -> None:
    document.status = DocumentStatus.pending
    document.error_message = None
    document.progress = 0
    document.progress_message = "等待重索引"
    document.page_count = None
    document.ocr_pages = 0
    document.toc_entries = None


async def find_reindexable_by_name(db: AsyncSession, filename: str) -> Document | None:
    result = await db.execute(
        select(Document)
        .where(Document.name == filename, Document.status.in_(REINDEXABLE_STATUSES))
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def schedule_document_reindex(db: AsyncSession, document: Document) -> Document:
    if document.status == DocumentStatus.deleting:
        raise ValueError("Document is being deleted")
    if document.status == DocumentStatus.pending:
        enqueue(process_document, str(document.id))
        return document
    if document.status == DocumentStatus.processing:
        # Worker may have crashed mid-parse; allow reindex to recover stuck jobs.
        pass

    reset_document_for_reindex(document)
    await db.commit()
    await db.refresh(document)
    enqueue(process_document, str(document.id))
    return document
