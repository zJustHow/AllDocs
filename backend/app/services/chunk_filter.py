from uuid import UUID

from pydantic import BaseModel, Field
from qdrant_client.http import models as qmodels


def chunk_asset_types(chunk: dict) -> list[str]:
    types = {
        str(asset.get("type"))
        for asset in chunk.get("assets") or []
        if asset.get("type")
    }
    return sorted(types)


class ChunkFilter(BaseModel):
    document_ids: list[UUID] | None = None
    asset_types: list[str] | None = None
    page_gte: int | None = Field(default=None, ge=1)
    page_lte: int | None = Field(default=None, ge=1)
    section_prefix: str | None = None
    section_contains: str | None = None

    @classmethod
    def from_request(
        cls,
        doc_ids: list[UUID] | None,
        filters: "ChunkFilter | None",
    ) -> "ChunkFilter":
        merged = filters.model_copy(deep=True) if filters else cls()
        if not doc_ids:
            return merged
        if merged.document_ids:
            doc_id_set = set(doc_ids)
            merged.document_ids = [doc_id for doc_id in merged.document_ids if doc_id in doc_id_set]
        else:
            merged.document_ids = list(doc_ids)
        return merged

    @classmethod
    def merge_sources(
        cls,
        doc_ids: list[UUID] | None,
        explicit: "ChunkFilter | None",
        inferred: "ChunkFilter | None",
    ) -> "ChunkFilter":
        merged = inferred.model_copy(deep=True) if inferred else cls()
        if explicit:
            for key, value in explicit.model_dump(exclude_none=True).items():
                setattr(merged, key, value)
        return cls.from_request(doc_ids, merged if merged.has_constraints() else None)

    def has_constraints(self) -> bool:
        return any(
            [
                self.document_ids,
                self.asset_types,
                self.page_gte is not None,
                self.page_lte is not None,
                self.section_prefix,
                self.section_contains,
            ]
        )

    def has_metadata_constraints(self) -> bool:
        return any(
            [
                self.asset_types,
                self.page_gte is not None,
                self.page_lte is not None,
                self.section_prefix,
                self.section_contains,
            ]
        )

    def broad_filter(self) -> "ChunkFilter":
        """Keep document scope only; drop narrow metadata constraints."""
        return self.model_copy(
            update={
                "asset_types": None,
                "page_gte": None,
                "page_lte": None,
                "section_prefix": None,
                "section_contains": None,
            }
        )


def build_qdrant_filter(chunk_filter: ChunkFilter | None) -> qmodels.Filter | None:
    if chunk_filter is None:
        return None

    must: list[qmodels.Condition] = []
    if chunk_filter.document_ids:
        must.append(
            qmodels.FieldCondition(
                key="document_id",
                match=qmodels.MatchAny(any=[str(doc_id) for doc_id in chunk_filter.document_ids]),
            )
        )
    if chunk_filter.asset_types:
        must.append(
            qmodels.FieldCondition(
                key="asset_types",
                match=qmodels.MatchAny(any=chunk_filter.asset_types),
            )
        )
    if chunk_filter.page_gte is not None or chunk_filter.page_lte is not None:
        must.append(
            qmodels.FieldCondition(
                key="page",
                range=qmodels.Range(
                    gte=chunk_filter.page_gte,
                    lte=chunk_filter.page_lte,
                ),
            )
        )
    return qmodels.Filter(must=must) if must else None


def build_es_filters(chunk_filter: ChunkFilter | None) -> list[dict]:
    if chunk_filter is None:
        return []

    filters: list[dict] = []
    if chunk_filter.document_ids:
        filters.append(
            {"terms": {"document_id": [str(doc_id) for doc_id in chunk_filter.document_ids]}}
        )
    if chunk_filter.asset_types:
        filters.append({"terms": {"asset_types": chunk_filter.asset_types}})
    if chunk_filter.page_gte is not None or chunk_filter.page_lte is not None:
        page_range: dict[str, int] = {}
        if chunk_filter.page_gte is not None:
            page_range["gte"] = chunk_filter.page_gte
        if chunk_filter.page_lte is not None:
            page_range["lte"] = chunk_filter.page_lte
        filters.append({"range": {"page": page_range}})
    if chunk_filter.section_prefix:
        filters.append({"prefix": {"section": chunk_filter.section_prefix}})
    if chunk_filter.section_contains:
        filters.append({"wildcard": {"section": f"*{chunk_filter.section_contains}*"}})
    return filters


def chunk_matches(chunk: dict, chunk_filter: ChunkFilter) -> bool:
    if chunk_filter.document_ids:
        if chunk.get("document_id") not in {str(doc_id) for doc_id in chunk_filter.document_ids}:
            return False

    if chunk_filter.asset_types:
        types = set(chunk_asset_types(chunk))
        if not types.intersection(chunk_filter.asset_types):
            return False

    page = chunk.get("page")
    if chunk_filter.page_gte is not None and (page is None or page < chunk_filter.page_gte):
        return False
    if chunk_filter.page_lte is not None and (page is None or page > chunk_filter.page_lte):
        return False

    section = chunk.get("section") or ""
    if chunk_filter.section_prefix and not section.startswith(chunk_filter.section_prefix):
        return False
    if chunk_filter.section_contains and chunk_filter.section_contains not in section:
        return False

    return True


def filter_chunks(chunks: list[dict], chunk_filter: ChunkFilter | None) -> list[dict]:
    if chunk_filter is None or not chunk_filter.has_constraints():
        return chunks
    return [chunk for chunk in chunks if chunk_matches(chunk, chunk_filter)]
