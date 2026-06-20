"""Metadata for settings that can be overridden at runtime via the UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SettingType = Literal["string", "int", "float", "bool", "secret"]


@dataclass(frozen=True, slots=True)
class SettingField:
    key: str
    group: str
    field_type: SettingType

    @property
    def secret(self) -> bool:
        return self.field_type == "secret"


EDITABLE_FIELDS: tuple[SettingField, ...] = (
    # LLM
    SettingField("llm_api_base_url", "llm", "string"),
    SettingField("llm_api_key", "llm", "secret"),
    SettingField("llm_model", "llm", "string"),
    # Ingest captions
    SettingField("ingest_caption_enabled", "ingest_caption", "bool"),
    SettingField("ingest_caption_api_base_url", "ingest_caption", "string"),
    SettingField("ingest_caption_api_key", "ingest_caption", "secret"),
    SettingField("ingest_caption_model", "ingest_caption", "string"),
    SettingField("ingest_caption_max_per_page", "ingest_caption", "int"),
    # RAG
    SettingField("rag_retrieve_k", "rag", "int"),
    SettingField("rag_top_k", "rag", "int"),
    SettingField("rag_chunk_size", "rag", "int"),
    SettingField("rag_chunk_overlap", "rag", "int"),
    SettingField("rag_agent_max_steps", "rag", "int"),
    SettingField("rag_agent_max_retrievals", "rag", "int"),
    SettingField("rag_batch_search_max", "rag", "int"),
    SettingField("rag_step_align_min_score", "rag", "float"),
    SettingField("rag_min_rerank_score", "rag", "float"),
    SettingField("rag_min_retrieval_score", "rag", "float"),
    SettingField("embed_skip_table_when_answer_has_markdown", "rag", "bool"),
    SettingField("embed_skip_table_lookback", "rag", "int"),
    # Retrieval
    SettingField("rerank_enabled", "retrieval", "bool"),
    SettingField("hybrid_enabled", "retrieval", "bool"),
    SettingField("hybrid_rrf_k", "retrieval", "int"),
    # OCR
    SettingField("ocr_enabled", "ocr", "bool"),
    SettingField("ocr_lang", "ocr", "string"),
    SettingField("ocr_force", "ocr", "bool"),
)

EDITABLE_KEYS: frozenset[str] = frozenset(field.key for field in EDITABLE_FIELDS)
SECRET_KEYS: frozenset[str] = frozenset(field.key for field in EDITABLE_FIELDS if field.secret)
FIELD_BY_KEY: dict[str, SettingField] = {field.key: field for field in EDITABLE_FIELDS}

GROUP_ORDER: tuple[str, ...] = ("llm", "ingest_caption", "rag", "retrieval", "ocr")


def coerce_setting_value(field: SettingField, raw: str) -> Any:
    if field.field_type == "secret":
        return raw
    if field.field_type == "bool":
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean for {field.key}")
    if field.field_type == "int":
        return int(raw)
    if field.field_type == "float":
        return float(raw)
    return raw


def serialize_setting_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
