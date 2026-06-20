"""Shared fixtures for API tests (mock lifespan side effects)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient


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
    ):
        yield


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    with _patched_app_lifecycle():
        from app.main import app

        with TestClient(app) as client:
            yield client
