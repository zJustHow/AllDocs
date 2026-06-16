import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from app.config import get_settings
from app.db.models import Chunk, Document, DocumentStatus
from app.services.document_delete import (
    delete_external_stores,
    finalize_document_deletion,
    rollback_document_deletion,
)
from app.services.embedding import EmbeddingService, chunk_embedding_text
from app.services.fulltext_store import FulltextStore
from app.services.ingestion import IngestionService, toc_entry_to_dict
from app.services.storage import StorageService
from app.services.vector_store import VectorStore
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(settings.postgres_url_sync)
SyncSession = sessionmaker(bind=sync_engine)


def _set_progress(
    db: OrmSession,
    document: Document,
    progress: int,
    message: str | None = None,
) -> None:
    document.progress = min(max(progress, 0), 100)
    if message is not None:
        document.progress_message = message
    db.commit()


def _abort_if_deleting(db: OrmSession, document: Document) -> bool:
    db.refresh(document)
    return document.status == DocumentStatus.deleting


@celery_app.task(name="process_document")
def process_document(document_id: str) -> None:
    doc_uuid = uuid.UUID(document_id)
    with SyncSession() as db:
        document = db.get(Document, doc_uuid)
        if not document or document.status == DocumentStatus.deleting:
            return

        document.status = DocumentStatus.processing
        document.error_message = None
        _set_progress(db, document, 5, "开始处理")

        try:
            _set_progress(db, document, 10, "读取文件")
            if _abort_if_deleting(db, document):
                return
            file_bytes = StorageService().download(document.object_key)

            def on_page_progress(current: int, total: int) -> None:
                pct = 10 + int(45 * current / total)
                _set_progress(db, document, pct, f"解析第 {current}/{total} 页")

            parse_result = IngestionService().parse_document(
                file_bytes,
                document.name,
                on_page_progress=on_page_progress,
            )
            parsed_chunks = parse_result.chunks
            page_count = parse_result.page_count
            if not parsed_chunks:
                raise ValueError("No text extracted from document")

            if _abort_if_deleting(db, document):
                return

            settings = get_settings()
            vector_store = VectorStore()
            vector_store.delete_by_document(doc_uuid)
            if settings.hybrid_enabled:
                FulltextStore().delete_by_document(doc_uuid)

            db.query(Chunk).filter(Chunk.document_id == doc_uuid).delete()
            db.commit()

            _set_progress(db, document, 58, "保存文本块")
            chunk_rows: list[Chunk] = []
            for parsed in parsed_chunks:
                chunk = Chunk(
                    document_id=doc_uuid,
                    text=parsed.text,
                    page=parsed.page,
                    section=parsed.section,
                    chunk_index=parsed.chunk_index,
                    chunk_type=parsed.chunk_type,
                    content_role=parsed.content_role,
                )
                db.add(chunk)
                chunk_rows.append(chunk)
            db.flush()

            _set_progress(db, document, 65, "生成向量")
            if _abort_if_deleting(db, document):
                db.rollback()
                return
            vectors = EmbeddingService().embed_documents(
                [chunk_embedding_text(chunk.text, chunk.section) for chunk in chunk_rows]
            )
            payloads = [
                {
                    "document_id": str(doc_uuid),
                    "document_name": document.name,
                    "page": chunk.page,
                    "section": chunk.section,
                    "chunk_type": chunk.chunk_type,
                    "content_role": chunk.content_role,
                    "chunk_index": chunk.chunk_index,
                }
                for chunk in chunk_rows
            ]

            _set_progress(db, document, 80, "写入向量库")
            vector_store.upsert_chunks(
                chunk_ids=[chunk.id for chunk in chunk_rows],
                vectors=vectors,
                payloads=payloads,
            )

            if settings.hybrid_enabled:
                _set_progress(db, document, 90, "写入全文索引")
                fulltext_store = FulltextStore()
                fulltext_store.upsert_chunks(
                    chunk_ids=[chunk.id for chunk in chunk_rows],
                    texts=[chunk.text for chunk in chunk_rows],
                    payloads=payloads,
                )

            if _abort_if_deleting(db, document):
                vector_store.delete_by_document(doc_uuid)
                if settings.hybrid_enabled:
                    FulltextStore().delete_by_document(doc_uuid)
                db.rollback()
                return

            for chunk in chunk_rows:
                chunk.qdrant_point_id = str(chunk.id)

            document.status = DocumentStatus.ready
            document.page_count = page_count
            document.ocr_pages = parse_result.ocr_pages
            document.toc_entries = [
                toc_entry_to_dict(entry) for entry in parse_result.toc_entries
            ] or None
            document.error_message = None
            _set_progress(db, document, 100, "完成")
            db.commit()
        except Exception as exc:
            if _abort_if_deleting(db, document):
                return
            document.status = DocumentStatus.failed
            document.error_message = str(exc)
            document.progress = 0
            document.progress_message = None
            db.commit()
            raise


@celery_app.task(name="delete_document")
def delete_document(document_id: str) -> None:
    doc_uuid = uuid.UUID(document_id)
    with SyncSession() as db:
        document = db.get(Document, doc_uuid)
        if not document or document.status != DocumentStatus.deleting:
            return

        object_key = document.object_key
        try:
            delete_external_stores(doc_uuid, object_key)
        except Exception as exc:
            db.rollback()
            document = db.get(Document, doc_uuid)
            if document and document.status == DocumentStatus.deleting:
                rollback_document_deletion(db, document, exc)
            raise

        try:
            finalize_document_deletion(db, document)
        except Exception as exc:
            db.rollback()
            document = db.get(Document, doc_uuid)
            if document and document.status == DocumentStatus.deleting:
                rollback_document_deletion(db, document, exc)
            raise
