import uuid
from unittest.mock import MagicMock, patch

import app.services.fulltext_store as fulltext_module
from app.config import Settings
from app.services.chunk_filter import ChunkFilter
from app.services.fulltext_store import FulltextStore


def test_fulltext_search_builds_bool_query_and_maps_hits() -> None:
    client = MagicMock()
    client.search.return_value = {
        "hits": {
            "hits": [
                {"_id": "chunk-1", "_score": 2.5, "_source": {"chunk_id": "chunk-1"}},
                {"_id": "chunk-2", "_score": 1.2, "_source": {}},
            ]
        }
    }

    with patch.object(fulltext_module, "get_elasticsearch_client", return_value=client):
        fulltext_module._index_ready = True
        store = FulltextStore(Settings(elasticsearch_index="chunks"))
        doc_id = uuid.uuid4()
        hits = store.search(
            "伺服报警",
            top_k=2,
            chunk_filter=ChunkFilter(document_ids=[doc_id]),
        )

    assert hits == [("chunk-1", 2.5), ("chunk-2", 1.2)]
    query = client.search.call_args.kwargs["query"]
    assert "multi_match" in str(query["bool"]["must"])
    assert query["bool"]["filter"]


def test_fulltext_upsert_chunks_batches_documents() -> None:
    client = MagicMock()

    with (
        patch.object(fulltext_module, "get_elasticsearch_client", return_value=client),
        patch("app.services.fulltext_store.bulk") as bulk_mock,
    ):
        fulltext_module._index_ready = True
        settings = Settings(elasticsearch_index="chunks", elasticsearch_bulk_batch_size=2)
        store = FulltextStore(settings)
        chunk_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        store.upsert_chunks(
            chunk_ids,
            ["a", "b", "c"],
            [{"document_id": "d1"}, {"document_id": "d1"}, {"document_id": "d1"}],
            captions=["cap-a", "cap-b", "cap-c"],
        )

    assert bulk_mock.call_count == 1
    actions = bulk_mock.call_args.args[1]
    assert len(actions) == 3
    assert bulk_mock.call_args.kwargs["chunk_size"] == 2
    assert actions[0]["caption"] == "cap-a"


def test_fulltext_search_keyword_prefers_phrase_query() -> None:
    client = MagicMock()
    client.search.return_value = {
        "hits": {
            "hits": [
                {"_id": "chunk-1", "_score": 5.0, "_source": {"chunk_id": "chunk-1"}},
            ]
        }
    }

    with patch.object(fulltext_module, "get_elasticsearch_client", return_value=client):
        fulltext_module._index_ready = True
        store = FulltextStore(Settings(elasticsearch_index="chunks"))
        hits = store.search_keyword("E001", top_k=3)

    assert hits == [("chunk-1", 5.0)]
    query = client.search.call_args.kwargs["query"]
    should = query["bool"]["must"][0]["bool"]["should"]
    assert any("match_phrase" in clause for clause in should)
