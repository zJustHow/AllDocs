from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from jwt.exceptions import InvalidTokenError

from app.config import get_settings
from app.db.models import UserRole


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(*, user_id: uuid.UUID, role: UserRole) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise InvalidTokenError("Invalid token type")
    return payload


def create_refresh_token_value() -> str:
    return secrets.token_urlsafe(48)


def refresh_token_expires_at() -> datetime:
    settings = get_settings()
    return datetime.now(UTC) + timedelta(days=settings.jwt_refresh_ttl_days)


def create_oauth_state(provider: str, *, bind_user_id: uuid.UUID | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "type": "oauth_state",
        "provider": provider,
        "iat": now,
        "exp": now + timedelta(minutes=10),
        "nonce": secrets.token_urlsafe(8),
    }
    if bind_user_id is not None:
        payload["bind_user_id"] = str(bind_user_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def parse_oauth_state(state: str, provider: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    except InvalidTokenError as exc:
        raise InvalidTokenError("Invalid OAuth state") from exc
    if payload.get("type") != "oauth_state" or payload.get("provider") != provider:
        raise InvalidTokenError("Invalid OAuth state")
    return payload


def verify_oauth_state(state: str, provider: str) -> None:
    parse_oauth_state(state, provider)
