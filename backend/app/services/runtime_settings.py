"""Runtime overrides for editable settings (stored in PostgreSQL)."""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, _env_settings
from app.db.models import AppSetting
from app.services.settings_registry import (
    EDITABLE_KEYS,
    FIELD_BY_KEY,
    GROUP_ORDER,
    coerce_setting_value,
    serialize_setting_value,
)

_lock = threading.Lock()
_overrides: dict[str, str] = {}


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{'*' * 8}{value[-4:]}"


def get_overrides() -> dict[str, str]:
    with _lock:
        return dict(_overrides)


def invalidate_service_caches() -> None:
    from app.services.deps import get_agent_service
    from app.services.fulltext_store import reset_fulltext_store_cache
    from app.services.storage import reset_storage_cache
    from app.services.vector_store import reset_vector_store_cache

    get_agent_service.cache_clear()
    reset_storage_cache()
    reset_vector_store_cache()
    reset_fulltext_store_cache()


def set_overrides(overrides: dict[str, str]) -> None:
    global _overrides
    with _lock:
        _overrides = dict(overrides)
    invalidate_service_caches()


def load_overrides_from_session(session: Session) -> dict[str, str]:
    rows = session.scalars(select(AppSetting)).all()
    return {row.key: row.value for row in rows if row.key in EDITABLE_KEYS}


def refresh_from_session(session: Session) -> dict[str, str]:
    overrides = load_overrides_from_session(session)
    set_overrides(overrides)
    return overrides


def apply_overrides(base: Settings, overrides: dict[str, str] | None = None) -> Settings:
    overrides = overrides if overrides is not None else get_overrides()
    if not overrides:
        return base

    typed: dict[str, Any] = {}
    for key, raw in overrides.items():
        field = FIELD_BY_KEY.get(key)
        if field is None:
            continue
        typed[key] = coerce_setting_value(field, raw)
    if not typed:
        return base
    return base.model_copy(update=typed)


def build_settings_response() -> dict[str, Any]:
    env = _env_settings()
    overrides = get_overrides()
    effective = apply_overrides(env, overrides)

    groups: dict[str, list[dict[str, Any]]] = {group: [] for group in GROUP_ORDER}
    for field in FIELD_BY_KEY.values():
        default = getattr(env, field.key)
        overridden = field.key in overrides
        entry: dict[str, Any] = {
            "key": field.key,
            "type": field.field_type,
            "secret": field.secret,
            "default": default,
            "overridden": overridden,
        }
        if field.secret:
            current = getattr(effective, field.key)
            entry["set"] = bool(current)
            entry["value"] = None
            entry["masked"] = mask_secret(current) if current else None
        else:
            entry["value"] = getattr(effective, field.key)
        groups[field.group].append(entry)

    return {
        "groups": [{"id": group_id, "fields": groups[group_id]} for group_id in GROUP_ORDER],
    }


def _audit_setting_value(key: str, value: Any) -> Any:
    field = FIELD_BY_KEY[key]
    if field.secret:
        return mask_secret(str(value)) if value else None
    return value


def update_overrides(session: Session, values: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    current = load_overrides_from_session(session)
    env = _env_settings()
    effective = apply_overrides(env, current)
    changes: dict[str, dict[str, Any]] = {}

    def record_change(key: str, old_value: Any, new_value: Any) -> None:
        old_display = _audit_setting_value(key, old_value)
        field = FIELD_BY_KEY[key]
        if field.secret:
            new_display = "(updated)" if new_value else None
        else:
            new_display = _audit_setting_value(key, new_value)
        if old_display != new_display:
            changes[key] = {"from": old_display, "to": new_display}

    for key, raw_value in values.items():
        if key not in EDITABLE_KEYS:
            raise ValueError(f"Unknown setting: {key}")

        field = FIELD_BY_KEY[key]
        if raw_value is None:
            if key in current:
                old_value = getattr(effective, key)
                current.pop(key, None)
                record_change(key, old_value, getattr(env, key))
            continue

        if field.secret:
            if raw_value == "":
                continue
            if not isinstance(raw_value, str):
                raise ValueError(f"Secret setting {key} must be a string")
            serialized = serialize_setting_value(raw_value)
        else:
            if field.field_type == "bool" and isinstance(raw_value, bool):
                serialized = serialize_setting_value(raw_value)
            elif field.field_type in {"int", "float"} and isinstance(raw_value, (int, float)):
                serialized = serialize_setting_value(raw_value)
            elif isinstance(raw_value, str):
                coerce_setting_value(field, raw_value)
                serialized = raw_value if field.field_type == "string" else serialize_setting_value(
                    coerce_setting_value(field, raw_value)
                )
            else:
                serialized = serialize_setting_value(raw_value)
                coerce_setting_value(field, serialized)

        default = getattr(env, key)
        current_value = getattr(effective, key)
        if field.secret:
            compare_value = current_value if key in current else ""
        else:
            compare_value = current_value

        if serialized == serialize_setting_value(default) and not field.secret:
            if key in current:
                current.pop(key, None)
                record_change(key, current_value, default)
        elif field.secret and serialized == serialize_setting_value(compare_value) and key in current:
            continue
        else:
            new_value = coerce_setting_value(field, serialized)
            if key not in current or current[key] != serialized:
                record_change(key, current_value, new_value)
            current[key] = serialized

    session.execute(delete(AppSetting))
    for key, value in current.items():
        session.add(AppSetting(key=key, value=value))
    session.commit()

    set_overrides(current)
    return current, changes
