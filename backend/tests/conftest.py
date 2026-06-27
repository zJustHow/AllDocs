"""Shared fixtures for API tests (mock lifespan side effects)."""

from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient


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
        patch("app.db.session.init_db", AsyncMock()),
        patch("app.db.session.async_session_factory", _session_factory),
        patch("app.services.runtime_settings.refresh_from_session", AsyncMock()),
        patch("app.services.infra_init.ensure_external_stores_async", AsyncMock()),
        patch("app.config.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth_disabled = True
        settings.metrics_enabled = True
        settings.log_level = "INFO"
        settings.cors_origin_list = lambda: ["http://localhost:3000"]
        mock_settings.return_value = settings
        _install_import_stubs()
        yield


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    with _patched_app_lifecycle():
        from app.main import app

        with TestClient(app) as client:
            yield client
