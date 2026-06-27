from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from jwt.exceptions import InvalidTokenError

from app.db.models import UserRole
from app.services.auth_tokens import (
    create_access_token,
    create_oauth_state,
    create_refresh_token_value,
    decode_access_token,
    hash_refresh_token,
    parse_oauth_state,
    refresh_token_expires_at,
    verify_oauth_state,
)


@pytest.fixture
def jwt_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        jwt_secret="test-secret",
        jwt_access_ttl_minutes=30,
        jwt_refresh_ttl_days=14,
    )
    monkeypatch.setattr("app.services.auth_tokens.get_settings", lambda: settings)


def test_hash_refresh_token_is_stable() -> None:
    assert hash_refresh_token("abc") == hash_refresh_token("abc")
    assert hash_refresh_token("abc") != hash_refresh_token("def")


def test_create_and_decode_access_token(jwt_settings: None) -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, role=UserRole.admin)
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["role"] == UserRole.admin.value
    assert payload["type"] == "access"


def test_decode_access_token_rejects_wrong_type(jwt_settings: None) -> None:
    settings = SimpleNamespace(
        jwt_secret="test-secret",
        jwt_access_ttl_minutes=30,
        jwt_refresh_ttl_days=14,
    )
    import jwt

    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "role": "user"},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(InvalidTokenError, match="Invalid token type"):
        decode_access_token(token)


def test_refresh_token_helpers(jwt_settings: None) -> None:
    value = create_refresh_token_value()
    assert len(value) >= 32
    expires = refresh_token_expires_at()
    assert expires.tzinfo is not None


def test_oauth_state_round_trip(jwt_settings: None) -> None:
    bind_user_id = uuid.uuid4()
    state = create_oauth_state("wechat", bind_user_id=bind_user_id)
    payload = parse_oauth_state(state, "wechat")

    assert payload["type"] == "oauth_state"
    assert payload["provider"] == "wechat"
    assert payload["bind_user_id"] == str(bind_user_id)
    verify_oauth_state(state, "wechat")


def test_oauth_state_rejects_wrong_provider(jwt_settings: None) -> None:
    state = create_oauth_state("wechat")
    with pytest.raises(InvalidTokenError, match="Invalid OAuth state"):
        parse_oauth_state(state, "github")
