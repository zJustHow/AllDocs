import uuid

from qdrant_client.http import models as qmodels

from app.services.chunk_filter import (
    ChunkFilter,
    build_es_filters,
    build_qdrant_filter,
    chunk_asset_types,
    chunk_matches,
    filter_chunks,
)


def test_chunk_filter_merge_sources_prefers_explicit_metadata() -> None:
    doc_id = uuid.uuid4()
    inferred = ChunkFilter(page_gte=2, section_prefix="Chapter")
    explicit = ChunkFilter(page_lte=5, asset_types=["table"])

    merged = ChunkFilter.merge_sources([doc_id], explicit, inferred)

    assert merged.document_ids == [doc_id]
    assert merged.page_lte == 5
    assert merged.page_gte == 2
    assert merged.section_prefix == "Chapter"
    assert merged.asset_types == ["table"]


def test_chunk_filter_broad_filter_keeps_documents_only() -> None:
    doc_id = uuid.uuid4()
    narrow = ChunkFilter(
        document_ids=[doc_id],
        page_gte=3,
        section_contains="故障",
        asset_types=["figure"],
    )

    broad = narrow.broad_filter()

    assert broad.document_ids == [doc_id]
    assert broad.page_gte is None
    assert broad.section_contains is None
    assert broad.asset_types is None


def test_build_qdrant_filter_includes_document_and_page_range() -> None:
    doc_id = uuid.uuid4()
    chunk_filter = ChunkFilter(document_ids=[doc_id], page_gte=2, page_lte=8)
    query_filter = build_qdrant_filter(chunk_filter)

    assert query_filter is not None
    assert len(query_filter.must) == 2
    assert isinstance(query_filter.must[0], qmodels.FieldCondition)
    assert isinstance(query_filter.must[1], qmodels.FieldCondition)


def test_build_es_filters_maps_metadata_fields() -> None:
    doc_id = uuid.uuid4()
    chunk_filter = ChunkFilter(
        document_ids=[doc_id],
        asset_types=["table"],
        section_prefix="Intro",
        section_contains="alarm",
    )
    filters = build_es_filters(chunk_filter)

    assert {"terms": {"document_id": [str(doc_id)]}} in filters
    assert {"terms": {"asset_types": ["table"]}} in filters
    assert {"prefix": {"section": "Intro"}} in filters
    assert {"wildcard": {"section": "*alarm*"}} in filters


def test_filter_chunks_applies_section_and_asset_constraints() -> None:
    doc_id = str(uuid.uuid4())
    chunks = [
        {
            "document_id": doc_id,
            "page": 2,
            "section": "Chapter 1",
            "assets": [{"type": "figure"}],
        },
        {
            "document_id": doc_id,
            "page": 9,
            "section": "Appendix",
            "assets": [{"type": "table"}],
        },
    ]
    chunk_filter = ChunkFilter(
        document_ids=[uuid.UUID(doc_id)],
        page_lte=5,
        asset_types=["figure"],
    )

    filtered = filter_chunks(chunks, chunk_filter)

    assert filtered == [chunks[0]]


def test_chunk_asset_types_returns_sorted_unique_types() -> None:
    chunk = {
        "assets": [
            {"type": "table"},
            {"type": "figure"},
            {"type": "figure"},
        ]
    }

    assert chunk_asset_types(chunk) == ["figure", "table"]
    assert chunk_matches(chunk, ChunkFilter(asset_types=["table"]))
