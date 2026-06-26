"""HTTP integration tests for auth, admin users, unbind, and audit logs."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.db.models import Base, UserRole
from app.db.session import get_db
from app.services.auth_service import bind_phone_to_user, register_with_email


def _install_import_stubs() -> None:
    for module_name in ("faster_whisper", "piper", "minio"):
        sys.modules.setdefault(module_name, MagicMock())

    if "celery" not in sys.modules:
        celery_mod = MagicMock()
        celery_app = MagicMock()
        celery_app.task = lambda *args, **kwargs: (lambda fn: fn)
        celery_mod.Celery.return_value = celery_app
        sys.modules["celery"] = celery_mod


@contextmanager
def _auth_api_context(session_factory: async_sessionmaker[AsyncSession]) -> Generator[None, None, None]:
    async def override_get_db() -> Generator[AsyncSession, None, None]:
        async with session_factory() as session:
            yield session

    mock_db = AsyncMock()
    mock_db.run_sync = AsyncMock()

    class _SessionCtx:
        async def __aenter__(self) -> AsyncMock:
            return mock_db

        async def __aexit__(self, *_args: object) -> None:
            return None

    settings = MagicMock()
    settings.auth_disabled = False
    settings.metrics_enabled = False
    settings.log_level = "INFO"
    settings.jwt_secret = "test-jwt-secret"
    settings.jwt_access_ttl_minutes = 30
    settings.jwt_refresh_ttl_days = 14

    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=MagicMock()),
        patch("app.db.session.init_db", AsyncMock()),
        patch("app.db.session.async_session_factory", lambda: _SessionCtx()),
        patch("app.services.runtime_settings.refresh_from_session", AsyncMock()),
        patch("app.services.infra_init.ensure_external_stores_async", AsyncMock()),
        patch("app.config.get_settings", return_value=settings),
        patch("app.api.auth_deps.get_settings", return_value=settings),
        patch("app.services.auth_tokens.get_settings", return_value=settings),
    ):
        _install_import_stubs()
        from app.main import app

        app.dependency_overrides[get_db] = override_get_db
        try:
            yield
        finally:
            app.dependency_overrides.clear()


async def _seed_auth_users(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, str]:
    async with session_factory() as session:
        admin, admin_access, _ = await register_with_email(
            session,
            email="admin@test.com",
            password="password123",
            role=UserRole.admin,
        )
        user, user_access, _ = await register_with_email(
            session,
            email="user@test.com",
            password="password123",
        )
        await bind_phone_to_user(session, user, "+8613800138000")
        await session.commit()
        return {
            "admin_token": admin_access,
            "user_token": user_access,
            "admin_id": str(admin.id),
            "user_id": str(user.id),
        }


@pytest.fixture
def auth_api_client() -> Generator[tuple[TestClient, dict[str, str]], None, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def init_db_schema() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init_db_schema())
    tokens = asyncio.run(_seed_auth_users(session_factory))

    with _auth_api_context(session_factory):
        from app.main import app

        with TestClient(app) as client:
            yield client, tokens

    asyncio.run(engine.dispose())


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_me_returns_profile(auth_api_client) -> None:
    client, tokens = auth_api_client
    response = client.get("/api/v1/auth/me", headers=_auth_headers(tokens["user_token"]))
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "user@test.com"
    assert payload["phone"] == "+8613800138000"
    assert payload["role"] == "user"


def test_unbind_last_identity_rejected(auth_api_client) -> None:
    client, _tokens = auth_api_client
    register = client.post(
        "/api/v1/auth/register/email",
        json={"email": "solo@test.com", "password": "password123"},
    )
    assert register.status_code == 200
    solo_token = register.json()["access_token"]

    response = client.delete(
        "/api/v1/auth/bind/email",
        headers=_auth_headers(solo_token),
    )
    assert response.status_code == 400
    assert "only login method" in response.json()["detail"].lower()


def test_unbind_email_when_phone_bound(auth_api_client) -> None:
    client, tokens = auth_api_client
    response = client.delete(
        "/api/v1/auth/bind/email",
        headers=_auth_headers(tokens["user_token"]),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] is None
    assert payload["phone"] == "+8613800138000"


def test_admin_users_requires_admin(auth_api_client) -> None:
    client, tokens = auth_api_client
    response = client.get("/api/v1/admin/users", headers=_auth_headers(tokens["user_token"]))
    assert response.status_code == 403


def test_admin_lists_users_and_writes_audit_log(auth_api_client) -> None:
    client, tokens = auth_api_client
    headers = _auth_headers(tokens["admin_token"])

    list_response = client.get("/api/v1/admin/users", headers=headers)
    assert list_response.status_code == 200
    users = list_response.json()["users"]
    assert len(users) >= 2

    target = next(item for item in users if item["id"] == tokens["user_id"])
    assert target["role"] == "user"

    patch_response = client.patch(
        f"/api/v1/admin/users/{tokens['user_id']}",
        headers=headers,
        json={"display_name": "Renamed User"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["display_name"] == "Renamed User"

    audit_response = client.get("/api/v1/admin/audit-logs", headers=headers)
    assert audit_response.status_code == 200
    logs = audit_response.json()["logs"]
    assert len(logs) >= 1
    assert logs[0]["action"] == "user.update"
    assert logs[0]["target_user_id"] == tokens["user_id"]
    assert "display_name" in (logs[0]["details"] or {})


def test_login_email_returns_tokens(auth_api_client) -> None:
    client, _tokens = auth_api_client
    response = client.post(
        "/api/v1/auth/login/email",
        json={"email": "admin@test.com", "password": "password123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["token_type"] == "bearer"


def test_register_email_otp_send_rejects_existing_email(auth_api_client) -> None:
    client, _tokens = auth_api_client
    response = client.post(
        "/api/v1/auth/register/email-otp/send",
        json={"email": "admin@test.com"},
    )
    assert response.status_code == 409
