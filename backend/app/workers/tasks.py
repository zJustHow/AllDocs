import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from app.config import get_settings
from app.db.models import Chunk, Document, DocumentStatus
from app.services.embedding import EmbeddingService
from app.services.fulltext_store import FulltextStore
from app.services.ingestion import IngestionService
from app.services.storage import StorageService
from app.services.vector_store import VectorStore
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(settings.postgres_url_sync)
SyncSession = sessionmaker(bind=sync_engine)


@celery_app.task(name="process_document")
def process_document(document_id: str) -> None:
    doc_uuid = uuid.UUID(document_id)
    with SyncSession() as db:
        document = db.get(Document, doc_uuid)
        if not document:
            return

        document.status = DocumentStatus.processing
        document.error_message = None
        db.commit()

        try:
            file_bytes = StorageService().download(document.object_key)
            parse_result = IngestionService().parse_pdf(file_bytes)
            parsed_chunks = parse_result.chunks
            page_count = parse_result.page_count
            if not parsed_chunks:
                raise ValueError("No text extracted from PDF")

            db.query(Chunk).filter(Chunk.document_id == doc_uuid).delete()
            db.commit()

            chunk_rows: list[Chunk] = []
            for parsed in parsed_chunks:
                chunk = Chunk(
                    document_id=doc_uuid,
                    text=parsed.text,
                    page=parsed.page,
                    section=parsed.section,
                    chunk_index=parsed.chunk_index,
                    chunk_type=parsed.chunk_type,
                )
                db.add(chunk)
                chunk_rows.append(chunk)
            db.flush()

            vectors = EmbeddingService().embed_documents([chunk.text for chunk in chunk_rows])
            payloads = [
                {
                    "document_id": str(doc_uuid),
                    "document_name": document.name,
                    "page": chunk.page,
                    "section": chunk.section,
                    "chunk_type": chunk.chunk_type,
                    "chunk_index": chunk.chunk_index,
                }
                for chunk in chunk_rows
            ]
            vector_store = VectorStore()
            vector_store.upsert_chunks(
                chunk_ids=[chunk.id for chunk in chunk_rows],
                vectors=vectors,
                payloads=payloads,
            )

            settings = get_settings()
            if settings.hybrid_enabled:
                fulltext_store = FulltextStore()
                fulltext_store.delete_by_document(doc_uuid)
                fulltext_store.upsert_chunks(
                    chunk_ids=[chunk.id for chunk in chunk_rows],
                    texts=[chunk.text for chunk in chunk_rows],
                    payloads=payloads,
                )

            for chunk in chunk_rows:
                chunk.qdrant_point_id = str(chunk.id)

            document.status = DocumentStatus.ready
            document.page_count = page_count
            document.ocr_pages = parse_result.ocr_pages
            document.error_message = None
            db.commit()
        except Exception as exc:
            document.status = DocumentStatus.failed
            document.error_message = str(exc)
            db.commit()
            raise
