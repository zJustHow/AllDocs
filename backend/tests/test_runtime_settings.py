from app.config import _env_settings
from app.services.runtime_settings import (
    apply_overrides,
    build_settings_response,
    mask_secret,
    set_overrides,
)
from app.services.settings_registry import coerce_setting_value, serialize_setting_value


def test_mask_secret_short_value() -> None:
    assert mask_secret("ab") == "****"


def test_mask_secret_long_value() -> None:
    assert mask_secret("sk-abcdefghijklmnop").endswith("mnop")
    assert mask_secret("sk-abcdefghijklmnop").startswith("*")


def test_apply_overrides_merges_typed_values() -> None:
    base = _env_settings()
    merged = apply_overrides(base, {"rag_top_k": "5", "hybrid_enabled": "false"})
    assert merged.rag_top_k == 5
    assert merged.hybrid_enabled is False
    assert merged.llm_model == base.llm_model


def test_build_settings_response_marks_overrides() -> None:
    set_overrides({"rag_top_k": "7"})
    try:
        payload = build_settings_response()
        rag_fields = next(group for group in payload["groups"] if group["id"] == "rag")["fields"]
        top_k = next(field for field in rag_fields if field["key"] == "rag_top_k")
        assert top_k["value"] == 7
        assert top_k["overridden"] is True
    finally:
        set_overrides({})


def test_build_settings_response_includes_pdf_table_header_group() -> None:
    payload = build_settings_response()
    group_ids = [group["id"] for group in payload["groups"]]
    assert "pdf_table_header" in group_ids
    header_fields = next(
        group for group in payload["groups"] if group["id"] == "pdf_table_header"
    )["fields"]
    keys = {field["key"] for field in header_fields}
    assert keys == {
        "pdf_table_header_detect_enabled",
        "pdf_table_header_y_tolerance",
        "pdf_table_header_margin",
        "pdf_table_header_top_padding",
        "pdf_table_header_clip_bottom_ratio",
        "pdf_table_header_snap_y_tolerance",
        "pdf_table_header_join_y_tolerance",
    }


def test_apply_overrides_pdf_table_header() -> None:
    base = _env_settings()
    merged = apply_overrides(
        base,
        {
            "pdf_table_header_detect_enabled": "false",
            "pdf_table_header_y_tolerance": "12.5",
        },
    )
    assert merged.pdf_table_header_detect_enabled is False
    assert merged.pdf_table_header_y_tolerance == 12.5


def test_invalidate_service_caches_clears_infra_clients() -> None:
    from app.services.deps import get_agent_service
    from app.services.fulltext_store import get_elasticsearch_client
    from app.services.runtime_settings import invalidate_service_caches
    from app.services.storage import get_minio_client
    from app.services.vector_store import get_qdrant_client

    agent_before = get_agent_service()
    minio_before = get_minio_client()
    qdrant_before = get_qdrant_client()
    es_before = get_elasticsearch_client()

    invalidate_service_caches()

    assert get_agent_service() is not agent_before
    assert get_minio_client() is not minio_before
    assert get_qdrant_client() is not qdrant_before
    assert get_elasticsearch_client() is not es_before


def test_coerce_setting_value() -> None:
    from app.services.settings_registry import FIELD_BY_KEY

    field = FIELD_BY_KEY["hybrid_enabled"]
    assert coerce_setting_value(field, "true") is True
    assert serialize_setting_value(True) == "true"
