from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from qdrant_client.http import models as qmodels

import app.services.vector_store as vector_store_module
from app.config import Settings
from app.services.chunk_filter import ChunkFilter
from app.services.vector_store import VectorStore


@pytest.fixture
def mock_qdrant() -> MagicMock:
    client = MagicMock()
    with patch.object(vector_store_module, "get_qdrant_client", return_value=client):
        vector_store_module._collection_ready = True
        yield client
    vector_store_module._collection_ready = False


def test_upsert_chunks_batches_points(mock_qdrant: MagicMock) -> None:
    settings = Settings(qdrant_collection="chunks", qdrant_upsert_batch_size=2)
    store = VectorStore(settings)
    chunk_ids = [uuid4(), uuid4(), uuid4()]
    vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    payloads = [{"document_id": "d1"}, {"document_id": "d1"}, {"document_id": "d2"}]

    store.upsert_chunks(chunk_ids, vectors, payloads)

    assert mock_qdrant.upsert.call_count == 2
    first_points = mock_qdrant.upsert.call_args_list[0].kwargs["points"]
    assert len(first_points) == 2
    assert isinstance(first_points[0], qmodels.PointStruct)


def test_search_passes_filter_and_limit(mock_qdrant: MagicMock) -> None:
    mock_qdrant.search.return_value = []
    settings = Settings(qdrant_collection="chunks")
    store = VectorStore(settings)
    doc_id = uuid4()
    chunk_filter = ChunkFilter(document_ids=[doc_id])

    hits = store.search([0.1, 0.2, 0.3], top_k=5, chunk_filter=chunk_filter)

    assert hits == []
    mock_qdrant.search.assert_called_once()
    call_kwargs = mock_qdrant.search.call_args.kwargs
    assert call_kwargs["limit"] == 5
    assert call_kwargs["collection_name"] == "chunks"
    assert call_kwargs["query_filter"] is not None


def test_delete_by_document_targets_document_id(mock_qdrant: MagicMock) -> None:
    settings = Settings(qdrant_collection="chunks")
    store = VectorStore(settings)
    document_id = uuid4()

    store.delete_by_document(document_id)

    selector = mock_qdrant.delete.call_args.kwargs["points_selector"]
    assert isinstance(selector, qmodels.FilterSelector)
