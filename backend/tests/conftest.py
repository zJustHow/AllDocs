"""Shared fixtures for API tests (mock lifespan side effects)."""

from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

_GET_SETTINGS_MODULES = (
    "app.api.auth_deps",
    "app.main",
    "app.api.chat",
    "app.api.documents",
    "app.services.auth_tokens",
    "app.services.auth_service",
    "app.services.rate_limit",
    "app.services.otp_service",
    "app.services.email_otp_service",
    "app.services.deps",
)


def _restore_get_settings_imports() -> None:
    from app.config import get_settings

    for name in _GET_SETTINGS_MODULES:
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "get_settings"):
            module.get_settings = get_settings


def _install_import_stubs() -> None:
    """Avoid loading speech/Celery stacks when importing the FastAPI app in CI."""
    for module_name in ("faster_whisper", "piper", "minio"):
        sys.modules.setdefault(module_name, MagicMock())

    if "celery" not in sys.modules:
        celery_mod = MagicMock()
        celery_app = MagicMock()
        celery_app.task = lambda *args, **kwargs: (lambda fn: fn)
        celery_mod.Celery.return_value = celery_app
        sys.modules["celery"] = celery_mod


@contextmanager
def _patched_app_lifecycle() -> Generator[None, None, None]:
    mock_db = AsyncMock()
    mock_db.run_sync = AsyncMock()

    class _SessionCtx:
        async def __aenter__(self) -> AsyncMock:
            return mock_db

        async def __aexit__(self, *_args: object) -> None:
            return None

    def _session_factory() -> _SessionCtx:
        return _SessionCtx()

    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=MagicMock()),
        patch("sqlalchemy.create_engine", return_value=MagicMock()),
        patch("app.db.session.init_db", AsyncMock()),
        patch("app.db.session.async_session_factory", _session_factory),
        patch("app.services.runtime_settings.refresh_from_session", AsyncMock()),
        patch("app.services.infra_init.ensure_external_stores_async", AsyncMock()),
    ):
        _install_import_stubs()
        from app.api.auth_deps import _dev_user, get_current_user, get_current_user_flexible
        from app.main import app

        async def _dev_user_dep() -> object:
            return _dev_user()

        overrides = {
            get_current_user: _dev_user_dep,
            get_current_user_flexible: _dev_user_dep,
        }
        app.dependency_overrides.update(overrides)
        try:
            yield
        finally:
            for dependency in overrides:
                app.dependency_overrides.pop(dependency, None)


@pytest.fixture(autouse=True)
def _reset_get_settings_bindings() -> Generator[None, None, None]:
    _restore_get_settings_imports()
    yield
    _restore_get_settings_imports()


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    with _patched_app_lifecycle():
        from app.main import app

        with TestClient(app) as client:
            yield client
