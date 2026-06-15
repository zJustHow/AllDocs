from functools import lru_cache
from uuid import UUID

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from app.config import Settings, get_settings
from app.services.chunk_filter import ChunkFilter, build_es_filters

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
            "page": {"type": "integer"},
            "section": {"type": "keyword"},
            "chunk_type": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
        }
    },
}


@lru_cache
def get_elasticsearch_client() -> Elasticsearch:
    settings = get_settings()
    return Elasticsearch(settings.elasticsearch_url)


class FulltextStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = get_elasticsearch_client()
        self.index = self.settings.elasticsearch_index
        self._ensure_index()

    def _ensure_index(self) -> None:
        if not self.client.indices.exists(index=self.index):
            self.client.indices.create(index=self.index, body=INDEX_BODY)

    def upsert_chunks(
        self,
        chunk_ids: list[UUID],
        texts: list[str],
        payloads: list[dict],
    ) -> None:
        actions = [
            {
                "_op_type": "index",
                "_index": self.index,
                "_id": str(chunk_id),
                "chunk_id": str(chunk_id),
                "text": text,
                **payload,
            }
            for chunk_id, text, payload in zip(chunk_ids, texts, payloads, strict=True)
        ]
        bulk(self.client, actions, refresh="wait_for")

    def search(
        self,
        query: str,
        top_k: int,
        chunk_filter: ChunkFilter | None = None,
    ) -> list[tuple[str, float]]:
        must: list[dict] = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["text^3", "section^2", "document_name"],
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

    def delete_by_document(self, document_id: UUID) -> None:
        self.client.delete_by_query(
            index=self.index,
            query={"term": {"document_id": str(document_id)}},
            refresh=True,
        )
