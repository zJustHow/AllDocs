from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.wechat_oauth import (
    WeChatOAuthError,
    build_frontend_bind_callback_url,
    build_frontend_callback_url,
    build_wechat_authorize_url,
    exchange_wechat_code,
    fetch_wechat_profile,
    wechat_oauth_enabled,
)


def _wechat_settings(**overrides: object) -> SimpleNamespace:
    base = {
        "wechat_app_id": "wx-app-id",
        "wechat_app_secret": "wx-secret",
        "wechat_redirect_uri": "https://app.example.com/api/v1/auth/wechat/callback",
        "auth_frontend_callback_url": "https://app.example.com/auth/callback",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_wechat_oauth_enabled_requires_all_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.wechat_oauth.get_settings",
        lambda: _wechat_settings(wechat_app_id=""),
    )
    assert wechat_oauth_enabled() is False

    monkeypatch.setattr("app.services.wechat_oauth.get_settings", lambda: _wechat_settings())
    assert wechat_oauth_enabled() is True


def test_build_wechat_authorize_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.wechat_oauth.get_settings", lambda: _wechat_settings())

    url = build_wechat_authorize_url("state-token")

    assert url.startswith("https://open.weixin.qq.com/connect/qrconnect?")
    assert "appid=wx-app-id" in url
    assert "state=state-token" in url
    assert url.endswith("#wechat_redirect")


def test_build_wechat_authorize_url_requires_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.wechat_oauth.get_settings",
        lambda: _wechat_settings(wechat_app_secret=""),
    )
    with pytest.raises(WeChatOAuthError, match="not configured"):
        build_wechat_authorize_url("state-token")


def test_build_frontend_callback_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.wechat_oauth.get_settings", lambda: _wechat_settings())

    login_url = build_frontend_callback_url(access_token="access", refresh_token="refresh")
    bind_url = build_frontend_bind_callback_url(provider="wechat", status="ok")

    assert login_url == "https://app.example.com/auth/callback#access_token=access&refresh_token=refresh"
    assert bind_url == "https://app.example.com/auth/callback#bind=wechat&status=ok"


def test_exchange_wechat_code_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.wechat_oauth.get_settings", lambda: _wechat_settings())

    response = MagicMock()
    response.json.return_value = {"openid": "openid-1", "access_token": "wx-access"}

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get = AsyncMock(return_value=response)

    with patch("app.services.wechat_oauth.httpx.AsyncClient", return_value=client):
        payload = asyncio.run(exchange_wechat_code("auth-code"))

    assert payload["openid"] == "openid-1"


def test_exchange_wechat_code_surfaces_api_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.wechat_oauth.get_settings", lambda: _wechat_settings())

    response = MagicMock()
    response.json.return_value = {"errcode": 40029, "errmsg": "invalid code"}

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get = AsyncMock(return_value=response)

    with patch("app.services.wechat_oauth.httpx.AsyncClient", return_value=client):
        with pytest.raises(WeChatOAuthError, match="invalid code"):
            asyncio.run(exchange_wechat_code("bad-code"))


def test_fetch_wechat_profile_returns_empty_on_error() -> None:
    response = MagicMock()
    response.json.return_value = {"errcode": 40001, "errmsg": "invalid credential"}

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get = AsyncMock(return_value=response)

    with patch("app.services.wechat_oauth.httpx.AsyncClient", return_value=client):
        profile = asyncio.run(fetch_wechat_profile("token", "openid"))

    assert profile == {}
