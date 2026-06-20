from functools import lru_cache
from threading import Lock
from uuid import UUID

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from app.config import Settings, get_settings
from app.services.chunk_filter import ChunkFilter, build_es_filters

_index_lock = Lock()
_index_ready = False

INDEX_BODY = {
    "settings": {
        "analysis": {
            "analyzer": {
                "manual_index_analyzer": {
                    "type": "custom",
                    "tokenizer": "ik_max_word",
                    "filter": ["lowercase"],
                },
                "manual_search_analyzer": {
                    "type": "custom",
                    "tokenizer": "ik_smart",
                    "filter": ["lowercase"],
                },
            }
        }
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "document_name": {"type": "keyword"},
            "text": {
                "type": "text",
                "analyzer": "manual_index_analyzer",
                "search_analyzer": "manual_search_analyzer",
            },
            "caption": {
                "type": "text",
                "analyzer": "manual_index_analyzer",
                "search_analyzer": "manual_search_analyzer",
            },
            "page": {"type": "integer"},
            "section": {"type": "keyword"},
            "asset_types": {"type": "keyword"},
        }
    },
}


@lru_cache
def get_elasticsearch_client() -> Elasticsearch:
    settings = get_settings()
    return Elasticsearch(settings.elasticsearch_url)


def _ensure_caption_mapping(client: Elasticsearch, index: str) -> None:
    mapping = client.indices.get_mapping(index=index)
    props = mapping.get(index, {}).get("mappings", {}).get("properties", {})
    updates: dict = {}
    if "caption" not in props:
        updates["caption"] = {
            "type": "text",
            "analyzer": "manual_index_analyzer",
            "search_analyzer": "manual_search_analyzer",
        }
    if "asset_types" not in props:
        updates["asset_types"] = {"type": "keyword"}
    if not updates:
        return
    client.indices.put_mapping(index=index, body={"properties": updates})


def ensure_index(settings: Settings | None = None) -> None:
    global _index_ready
    if _index_ready:
        return
    with _index_lock:
        if _index_ready:
            return
        settings = settings or get_settings()
        client = get_elasticsearch_client()
        index = settings.elasticsearch_index
        if not client.indices.exists(index=index):
            client.indices.create(index=index, body=INDEX_BODY)
        else:
            _ensure_caption_mapping(client, index)
        _index_ready = True


class FulltextStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = get_elasticsearch_client()
        self.index = self.settings.elasticsearch_index

    def upsert_chunks(
        self,
        chunk_ids: list[UUID],
        texts: list[str],
        payloads: list[dict],
        captions: list[str] | None = None,
    ) -> None:
        ensure_index(self.settings)
        caption_values = captions or [""] * len(chunk_ids)
        actions = [
            {
                "_op_type": "index",
                "_index": self.index,
                "_id": str(chunk_id),
                "chunk_id": str(chunk_id),
                "text": text,
                "caption": caption,
                **payload,
            }
            for chunk_id, text, caption, payload in zip(
                chunk_ids, texts, caption_values, payloads, strict=True
            )
        ]
        bulk(
            self.client,
            actions,
            refresh=False,
            chunk_size=max(1, self.settings.elasticsearch_bulk_batch_size),
        )

    def refresh_index(self) -> None:
        ensure_index(self.settings)
        self.client.indices.refresh(index=self.index)

    def search(
        self,
        query: str,
        top_k: int,
        chunk_filter: ChunkFilter | None = None,
    ) -> list[tuple[str, float]]:
        ensure_index(self.settings)
        must: list[dict] = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["text^3", "caption^2", "section^2", "document_name"],
                    "type": "best_fields",
                }
            }
        ]
        es_filters = build_es_filters(chunk_filter)
        bool_query: dict = {"must": must}
        if es_filters:
            bool_query["filter"] = es_filters

        response = self.client.search(
            index=self.index,
            query={"bool": bool_query},
            size=top_k,
        )
        hits: list[tuple[str, float]] = []
        for hit in response["hits"]["hits"]:
            chunk_id = hit["_source"].get("chunk_id") or hit["_id"]
            hits.append((str(chunk_id), float(hit["_score"])))
        return hits

    def search_keyword(
        self,
        query: str,
        top_k: int,
        chunk_filter: ChunkFilter | None = None,
    ) -> list[tuple[str, float]]:
        ensure_index(self.settings)
        query = query.strip()
        if not query:
            return []

        must: list[dict] = [
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"text": {"query": query, "boost": 3}}},
                        {"match_phrase": {"caption": {"query": query, "boost": 2}}},
                        {
                            "match": {
                                "text": {
                                    "query": query,
                                    "operator": "and",
                                }
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        ]
        es_filters = build_es_filters(chunk_filter)
        bool_query: dict = {"must": must}
        if es_filters:
            bool_query["filter"] = es_filters

        response = self.client.search(
            index=self.index,
            query={"bool": bool_query},
            size=top_k,
        )
        hits: list[tuple[str, float]] = []
        for hit in response["hits"]["hits"]:
            chunk_id = hit["_source"].get("chunk_id") or hit["_id"]
            hits.append((str(chunk_id), float(hit["_score"])))
        return hits

    def delete_by_document(self, document_id: UUID) -> None:
        ensure_index(self.settings)
        self.client.delete_by_query(
            index=self.index,
            query={"term": {"document_id": str(document_id)}},
            refresh=True,
        )
