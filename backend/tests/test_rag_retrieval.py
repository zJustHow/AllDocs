import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings
from app.services.rag import RAGService
from app.services.toc_lookup import (
    extract_toc_query,
    format_documents_outline,
    outline_to_chunks,
)


def test_extract_toc_query_parses_chapter_and_terms() -> None:
    chapter_index, terms = extract_toc_query("第三章「伺服系统」从哪页开始？")

    assert chapter_index == 3
    assert any("第三章" in term or "伺服" in term for term in terms)


def test_format_documents_outline_lists_sections() -> None:
    from app.db.models import Document

    document = Document(
        id=uuid.uuid4(),
        name="Manual.pdf",
        object_key="k",
        toc_entries=[
            {
                "title": "第一章 概述",
                "path": "第一章 概述",
                "level": 1,
                "start_page": 1,
                "end_page": 5,
            }
        ],
    )
    text = format_documents_outline([document])

    assert "Manual.pdf" in text
    assert "第一章 概述" in text
    assert "p.1-p.5" in text


def test_outline_to_chunks_builds_synthetic_entries() -> None:
    from app.db.models import Document

    document = Document(
        id=uuid.uuid4(),
        name="Manual.pdf",
        object_key="k",
        toc_entries=[
            {
                "title": "第二章",
                "path": "第二章",
                "level": 1,
                "start_page": 10,
                "end_page": 20,
            }
        ],
    )
    chunks = outline_to_chunks([document])

    assert len(chunks) == 1
    assert chunks[0]["section"] == "目录"
    assert chunks[0]["page"] == 10


def test_read_neighbor_chunks_returns_ordered_neighbors() -> None:
    doc_id = uuid.uuid4()
    anchor_id = uuid.uuid4()
    neighbor_id = uuid.uuid4()

    from app.db.models import Chunk, Document

    anchor = Chunk(
        id=anchor_id,
        document_id=doc_id,
        text="anchor",
        page=5,
        section="S",
        chunk_index=2,
    )

    class FakeScalarResult:
        def scalar_one_or_none(self):
            return anchor

        def all(self):
            return [(neighbor_id,), (anchor_id,)]

    db = AsyncMock()
    db.execute = AsyncMock(return_value=FakeScalarResult())

    settings = Settings(inference_url="http://inference", hybrid_enabled=False, rerank_enabled=False)
    with (
        patch("app.services.embedding_provider.get_embedding_service", return_value=MagicMock()),
        patch("app.services.rag.VectorStore", return_value=MagicMock()),
    ):
        rag = RAGService(settings)

    neighbor_chunk = {
        "chunk_id": str(neighbor_id),
        "document_name": "Manual",
        "page": 4,
        "text": "before",
        "snippet": "before",
        "assets": [],
    }
    anchor_chunk = {
        "chunk_id": str(anchor_id),
        "document_name": "Manual",
        "page": 5,
        "text": "anchor",
        "snippet": "anchor",
        "assets": [],
    }
    rag._load_chunks = AsyncMock(return_value=[neighbor_chunk, anchor_chunk])

    chunks, error = asyncio.run(
        rag.read_neighbor_chunks(db, str(anchor_id), before=1, after=0)
    )

    assert error is None
    assert len(chunks) == 2
    assert chunks[0]["chunk_id"] == str(neighbor_id)


def test_search_hybrid_fuses_vector_and_bm25() -> None:
    settings = Settings(inference_url="http://inference", hybrid_enabled=True, hybrid_rrf_k=60)
    with (
        patch("app.services.embedding_provider.get_embedding_service", return_value=MagicMock()),
        patch("app.services.rag.VectorStore", return_value=MagicMock()),
        patch("app.services.rag.FulltextStore", return_value=MagicMock()),
    ):
        rag = RAGService(settings)

    vector_hit = MagicMock()
    vector_hit.id = "vec-1"
    vector_hit.score = 0.9
    rag.vector_store.search = MagicMock(return_value=[vector_hit])
    rag.fulltext_store.search = MagicMock(return_value=[("bm25-1", 3.0)])

    ranked_ids, score_map = asyncio.run(
        rag._search_hybrid("alarm", [0.1, 0.2], retrieve_k=5, effective_filter=None)
    )

    assert "vec-1" in ranked_ids
    assert "bm25-1" in ranked_ids
    assert score_map
