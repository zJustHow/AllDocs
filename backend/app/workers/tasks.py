import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession, sessionmaker

from app.config import get_settings
from app.db.models import Chunk, ChunkAsset, Document, DocumentStatus
from app.services.document_delete import (
    delete_external_stores,
    finalize_document_deletion,
    rollback_document_deletion,
)
from app.services.embedding import chunk_embedding_text
from app.services.embedding_provider import get_embedding_service
from app.services.fulltext_store import FulltextStore
from app.services.ingest_caption import apply_ingest_captions
from app.services.asset_dedupe import AssetDedupeRegistry
from app.services.chunk_index import chunk_fulltext_caption
from app.services.ingestion import IngestionService, toc_entry_to_dict
from app.services.infra_init import ensure_external_stores
from app.services.storage import StorageService
from app.services.vector_store import VectorStore
from app.workers.celery_app import celery_app

settings = get_settings()
sync_engine = create_engine(
    settings.postgres_url_sync,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
SyncSession = sessionmaker(bind=sync_engine)

_PROGRESS_PAGE_INTERVAL = 5
_UPLOAD_WORKERS = 8


@dataclass(frozen=True)
class _PendingAssetUpload:
    asset_id: uuid.UUID
    chunk_id: uuid.UUID
    object_key: str
    png_bytes: bytes
    asset_type: str
    page: int
    bbox: list[float]
    width: int | None
    height: int | None
    text_summary: str = ""
    figure_caption: str | None = None
    figure_number: str | None = None
    needs_upload: bool = True


def _collect_pending_asset_uploads(
    doc_uuid: uuid.UUID,
    parsed_chunks,
    chunk_rows: list[Chunk],
) -> list[_PendingAssetUpload]:
    registry = AssetDedupeRegistry(doc_uuid)
    pending: list[_PendingAssetUpload] = []

    def append_asset(
        *,
        chunk_id: uuid.UUID,
        png_bytes: bytes,
        asset_type: str,
        page: int,
        bbox: list[float],
        width: int | None,
        height: int | None,
        text_summary: str = "",
        figure_caption: str | None = None,
        figure_number: str | None = None,
    ) -> None:
        asset_id, object_key, needs_upload = registry.resolve(png_bytes)
        pending.append(
            _PendingAssetUpload(
                asset_id=asset_id,
                chunk_id=chunk_id,
                object_key=object_key,
                png_bytes=png_bytes,
                asset_type=asset_type,
                page=page,
                bbox=bbox,
                width=width,
                height=height,
                text_summary=text_summary,
                figure_caption=figure_caption,
                figure_number=figure_number,
                needs_upload=needs_upload,
            )
        )

    for parsed, chunk in zip(parsed_chunks, chunk_rows, strict=True):
        for attached in parsed.attached_assets:
            append_asset(
                chunk_id=chunk.id,
                png_bytes=attached.png_bytes,
                asset_type=attached.asset_type,
                page=attached.page,
                bbox=list(attached.bbox),
                width=attached.width,
                height=attached.height,
                text_summary=attached.text_summary,
                figure_caption=attached.figure_caption,
                figure_number=attached.figure_number,
            )
    return pending


def _upload_assets_parallel(storage: StorageService, pending: list[_PendingAssetUpload]) -> None:
    to_upload = [item for item in pending if item.needs_upload]
    if not to_upload:
        return
    workers = min(_UPLOAD_WORKERS, len(to_upload))

    def _upload_one(item: _PendingAssetUpload) -> None:
        storage.upload(item.object_key, item.png_bytes, "image/png")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_upload_one, to_upload))


def _set_progress(
    db: OrmSession,
    document: Document,
    progress: int,
    message: str | None = None,
    *,
    commit: bool = True,
) -> None:
    document.progress = min(max(progress, 0), 100)
    if message is not None:
        document.progress_message = message
    if commit:
        db.commit()


def _throttled_page_progress(
    db: OrmSession,
    document: Document,
    *,
    interval: int = _PROGRESS_PAGE_INTERVAL,
):
    last_committed = 0

    def on_page_progress(current: int, total: int) -> None:
        nonlocal last_committed
        pct = 10 + int(45 * current / total)
        document.progress = min(max(pct, 0), 100)
        document.progress_message = f"解析第 {current}/{total} 页"
        if current == total or current - last_committed >= interval:
            db.commit()
            last_committed = current

    return on_page_progress


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
        ensure_external_stores()

        try:
            _set_progress(db, document, 10, "读取文件")
            if _abort_if_deleting(db, document):
                return
            file_bytes = StorageService().download(document.object_key)

            parse_result = IngestionService().parse_document(
                file_bytes,
                document.name,
                on_page_progress=_throttled_page_progress(db, document),
            )
            parsed_chunks = parse_result.chunks
            page_count = parse_result.page_count
            if not parsed_chunks:
                raise ValueError("No text extracted from document")

            if _abort_if_deleting(db, document):
                return

            storage = StorageService()
            storage.delete_prefix(f"{doc_uuid}/assets/")

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
                    layout_bbox=list(parsed.layout_bbox) if parsed.layout_bbox else None,
                )
                db.add(chunk)
                chunk_rows.append(chunk)
            db.flush()

            pending_assets = _collect_pending_asset_uploads(doc_uuid, parsed_chunks, chunk_rows)
            _upload_assets_parallel(storage, pending_assets)
            for item in pending_assets:
                initial_caption = item.text_summary.strip() if item.text_summary.strip() else None
                initial_figure_caption = (
                    item.figure_caption.strip()
                    if item.figure_caption and item.figure_caption.strip()
                    else None
                )
                db.add(
                    ChunkAsset(
                        id=item.asset_id,
                        chunk_id=item.chunk_id,
                        document_id=doc_uuid,
                        asset_type=item.asset_type,
                        page=item.page,
                        bbox=item.bbox,
                        object_key=item.object_key,
                        width=item.width,
                        height=item.height,
                        caption=initial_caption,
                        figure_caption=initial_figure_caption,
                        figure_number=item.figure_number,
                    )
                )
            db.flush()

            _set_progress(db, document, 62, "生成图像描述")
            if _abort_if_deleting(db, document):
                return
            apply_ingest_captions(
                db,
                document=document,
                chunk_rows=chunk_rows,
                file_bytes=file_bytes,
                filename=document.name,
                settings=settings,
                asset_image_bytes={
                    str(item.asset_id): item.png_bytes for item in pending_assets
                }
                if pending_assets
                else None,
            )

            asset_rows = (
                db.query(ChunkAsset).filter(ChunkAsset.document_id == doc_uuid).all()
            )
            assets_by_chunk: dict[str, list[ChunkAsset]] = {}
            for asset in asset_rows:
                assets_by_chunk.setdefault(str(asset.chunk_id), []).append(asset)

            def _asset_captions(chunk_id: uuid.UUID) -> list[str]:
                return [
                    asset.caption
                    for asset in assets_by_chunk.get(str(chunk_id), [])
                    if asset.caption
                ]

            def _asset_figure_captions(chunk_id: uuid.UUID) -> list[str]:
                return [
                    asset.figure_caption
                    for asset in assets_by_chunk.get(str(chunk_id), [])
                    if asset.figure_caption
                ]

            _set_progress(db, document, 65, "生成向量")
            if _abort_if_deleting(db, document):
                db.rollback()
                return
            embedding_texts = [
                chunk_embedding_text(
                    chunk.text,
                    chunk.section,
                    caption=chunk.caption,
                    asset_captions=_asset_captions(chunk.id),
                    asset_figure_captions=_asset_figure_captions(chunk.id),
                )
                for chunk in chunk_rows
            ]
            embedding_service = get_embedding_service(settings)
            embed_batch_size = settings.embedding_batch_size
            vectors: list[list[float]] = []
            total_batches = (len(embedding_texts) + embed_batch_size - 1) // embed_batch_size
            for batch_index, start in enumerate(
                range(0, len(embedding_texts), embed_batch_size), start=1
            ):
                batch = embedding_texts[start : start + embed_batch_size]
                vectors.extend(embedding_service.embed_documents(batch))
                if total_batches > 1:
                    pct = 65 + int(14 * batch_index / total_batches)
                    _set_progress(
                        db,
                        document,
                        pct,
                        f"生成向量 {batch_index}/{total_batches}",
                    )
                if _abort_if_deleting(db, document):
                    db.rollback()
                    return
            payloads = [
                {
                    "document_id": str(doc_uuid),
                    "document_name": document.name,
                    "page": chunk.page,
                    "section": chunk.section,
                    "asset_types": sorted(
                        {
                            asset.asset_type
                            for asset in assets_by_chunk.get(str(chunk.id), [])
                        }
                    ),
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
                    captions=[
                        chunk_fulltext_caption(
                            chunk.caption,
                            _asset_captions(chunk.id),
                            asset_figure_captions=_asset_figure_captions(chunk.id),
                        )
                        for chunk in chunk_rows
                    ],
                    payloads=payloads,
                )
                fulltext_store.refresh_index()

            if _abort_if_deleting(db, document):
                vector_store.delete_by_document(doc_uuid)
                if settings.hybrid_enabled:
                    FulltextStore().delete_by_document(doc_uuid)
                db.rollback()
                return

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
