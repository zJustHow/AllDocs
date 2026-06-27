from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jwt.exceptions import InvalidTokenError
from starlette.requests import Request

from app.api.auth_deps import get_current_user, get_current_user_flexible, require_admin
from app.db.models import UserRole


def _request(auth_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/documents",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_get_current_user_returns_dev_user_when_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.auth_deps.get_settings",
        lambda: SimpleNamespace(auth_disabled=True),
    )

    user = asyncio.run(get_current_user(_request(), None, AsyncMock()))

    assert user.role == UserRole.admin
    assert user.display_name == "Dev"


def test_get_current_user_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.auth_deps.get_settings",
        lambda: SimpleNamespace(auth_disabled=False),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_current_user(_request(), None, AsyncMock()))
    assert exc_info.value.status_code == 401


def test_get_current_user_accepts_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()
    active_user = SimpleNamespace(id=user_id, is_active=True, role=UserRole.user)
    monkeypatch.setattr(
        "app.api.auth_deps.get_settings",
        lambda: SimpleNamespace(auth_disabled=False),
    )

    with (
        patch("app.api.auth_deps.decode_access_token", return_value={"sub": str(user_id)}),
        patch("app.api.auth_deps.get_user_by_id", AsyncMock(return_value=active_user)),
    ):
        user = asyncio.run(
            get_current_user(
                _request("Bearer header-token"),
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="cred-token"),
                AsyncMock(),
            )
        )

    assert user is active_user


def test_get_current_user_flexible_accepts_query_token(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid.uuid4()
    active_user = SimpleNamespace(id=user_id, is_active=True, role=UserRole.user)
    monkeypatch.setattr(
        "app.api.auth_deps.get_settings",
        lambda: SimpleNamespace(auth_disabled=False),
    )

    with (
        patch("app.api.auth_deps.decode_access_token", return_value={"sub": str(user_id)}),
        patch("app.api.auth_deps.get_user_by_id", AsyncMock(return_value=active_user)),
    ):
        user = asyncio.run(get_current_user_flexible(_request(), None, "query-token", AsyncMock()))

    assert user is active_user


def test_get_current_user_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.auth_deps.get_settings",
        lambda: SimpleNamespace(auth_disabled=False),
    )

    with patch("app.api.auth_deps.decode_access_token", side_effect=InvalidTokenError("bad")):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                get_current_user(
                    _request("Bearer bad-token"),
                    HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token"),
                    AsyncMock(),
                )
            )
    assert exc_info.value.status_code == 401


def test_require_admin_rejects_non_admin_users() -> None:
    user = SimpleNamespace(role=UserRole.user)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_admin(user))
    assert exc_info.value.status_code == 403
