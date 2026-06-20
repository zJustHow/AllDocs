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


def test_coerce_setting_value() -> None:
    from app.services.settings_registry import FIELD_BY_KEY

    field = FIELD_BY_KEY["hybrid_enabled"]
    assert coerce_setting_value(field, "true") is True
    assert serialize_setting_value(True) == "true"
