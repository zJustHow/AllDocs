from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

WECHAT_QRCONNECT_URL = "https://open.weixin.qq.com/connect/qrconnect"
WECHAT_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
WECHAT_USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"


class WeChatOAuthError(Exception):
    pass


def wechat_oauth_enabled() -> bool:
    settings = get_settings()
    return bool(settings.wechat_app_id and settings.wechat_app_secret and settings.wechat_redirect_uri)


def build_wechat_authorize_url(state: str) -> str:
    settings = get_settings()
    if not wechat_oauth_enabled():
        raise WeChatOAuthError("WeChat OAuth is not configured")

    params = urlencode(
        {
            "appid": settings.wechat_app_id,
            "redirect_uri": settings.wechat_redirect_uri,
            "response_type": "code",
            "scope": "snsapi_login",
            "state": state,
        }
    )
    return f"{WECHAT_QRCONNECT_URL}?{params}#wechat_redirect"


async def exchange_wechat_code(code: str) -> dict:
    settings = get_settings()
    if not wechat_oauth_enabled():
        raise WeChatOAuthError("WeChat OAuth is not configured")

    params = {
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret,
        "code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(WECHAT_TOKEN_URL, params=params)
        payload = response.json()

    if payload.get("errcode"):
        logger.warning("WeChat token exchange failed: %s", payload)
        raise WeChatOAuthError(payload.get("errmsg") or "WeChat token exchange failed")

    openid = payload.get("openid")
    if not openid:
        raise WeChatOAuthError("WeChat response missing openid")
    return payload


async def fetch_wechat_profile(access_token: str, openid: str) -> dict:
    params = {
        "access_token": access_token,
        "openid": openid,
        "lang": "zh_CN",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(WECHAT_USERINFO_URL, params=params)
        payload = response.json()

    if payload.get("errcode"):
        logger.warning("WeChat userinfo failed: %s", payload)
        return {}
    return payload


def build_frontend_callback_url(*, access_token: str, refresh_token: str) -> str:
    settings = get_settings()
    base = settings.auth_frontend_callback_url.rstrip("/")
    fragment = urlencode(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
    )
    return f"{base}#{fragment}"


def build_frontend_bind_callback_url(*, provider: str, status: str = "ok") -> str:
    settings = get_settings()
    base = settings.auth_frontend_callback_url.rstrip("/")
    fragment = urlencode({"bind": provider, "status": status})
    return f"{base}#{fragment}"
