from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.config import get_settings
from app.db.models import Document, DocumentStatus, Session
from app.services.fulltext_store import FulltextStore
from app.services.storage import StorageService
from app.services.vector_store import VectorStore


def remove_document_from_sessions(db: OrmSession, document_id: UUID) -> None:
    doc_id_str = str(document_id)
    sessions = db.scalars(select(Session).where(Session.doc_ids.contains([doc_id_str]))).all()
    for session in sessions:
        session.doc_ids = [doc_id for doc_id in session.doc_ids if doc_id != doc_id_str]
        if not session.doc_ids:
            db.delete(session)


def delete_external_stores(document_id: UUID, object_key: str) -> None:
    StorageService().delete(object_key)
    VectorStore().delete_by_document(document_id)
    settings = get_settings()
    if settings.hybrid_enabled:
        FulltextStore().delete_by_document(document_id)


def rollback_document_deletion(db: OrmSession, document: Document, exc: Exception) -> None:
    rollback_status_value = document.progress_message
    if rollback_status_value:
        try:
            document.status = DocumentStatus(rollback_status_value)
        except ValueError:
            document.status = DocumentStatus.failed
    else:
        document.status = DocumentStatus.failed
    document.error_message = f"Delete failed: {exc}"
    document.progress_message = None
    db.commit()


def finalize_document_deletion(db: OrmSession, document: Document) -> None:
    remove_document_from_sessions(db, document.id)
    db.delete(document)
    db.commit()
