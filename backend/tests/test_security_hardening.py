from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import Settings, validate_settings_for_env
from app.services.rate_limit import check_rate_limit, enforce_auth_rate_limit


def _request(client_host: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login/email",
        "headers": [],
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_check_rate_limit_allows_within_window() -> None:
    key = f"test:{uuid.uuid4()}"
    check_rate_limit(key, max_attempts=2, window_seconds=60)
    check_rate_limit(key, max_attempts=2, window_seconds=60)


def test_check_rate_limit_blocks_excess_attempts() -> None:
    key = f"test:{uuid.uuid4()}"
    check_rate_limit(key, max_attempts=1, window_seconds=60)
    with pytest.raises(HTTPException) as exc_info:
        check_rate_limit(key, max_attempts=1, window_seconds=60)
    assert exc_info.value.status_code == 429


def test_enforce_auth_rate_limit_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        auth_login_rate_limit_attempts=1,
        auth_login_rate_limit_window_seconds=60,
    )
    monkeypatch.setattr("app.services.rate_limit.get_settings", lambda: settings)
    request = _request()
    enforce_auth_rate_limit(request)
    with pytest.raises(HTTPException) as exc_info:
        enforce_auth_rate_limit(request)
    assert exc_info.value.status_code == 429


def test_validate_settings_for_env_skips_non_production() -> None:
    settings = Settings(
        app_env="development",
        jwt_secret="change-me-in-production",
        auth_disabled=True,
    )
    validate_settings_for_env(settings)


def test_validate_settings_for_env_rejects_insecure_production() -> None:
    settings = Settings(app_env="production")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_settings_for_env(settings)

    settings = Settings(
        app_env="production",
        jwt_secret="strong-secret",
        auth_disabled=True,
    )
    with pytest.raises(RuntimeError, match="AUTH_DISABLED"):
        validate_settings_for_env(settings)

    settings = Settings(
        app_env="production",
        jwt_secret="strong-secret",
        auth_disabled=False,
    )
    with pytest.raises(RuntimeError, match="MINIO"):
        validate_settings_for_env(settings)

    settings = Settings(
        app_env="production",
        jwt_secret="strong-secret",
        auth_disabled=False,
        minio_access_key="prod-key",
        minio_secret_key="prod-secret",
    )
    validate_settings_for_env(settings)
