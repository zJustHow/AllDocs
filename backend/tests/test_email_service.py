from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.email_service import send_otp_email


def test_send_otp_email_console_provider_logs_only(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "app.services.email_service.get_settings",
        lambda: SimpleNamespace(email_provider="console"),
    )

    with caplog.at_level("INFO"):
        asyncio.run(send_otp_email("user@test.com", "123456"))

    assert any("123456" in record.message for record in caplog.records)


def test_send_otp_email_smtp_delegates_to_thread_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.email_service.get_settings",
        lambda: SimpleNamespace(email_provider="smtp"),
    )

    with patch("app.services.email_service._send_smtp_email") as send_smtp:
        asyncio.run(send_otp_email("user@test.com", "654321"))

    send_smtp.assert_awaited_once_with("user@test.com", "654321")


def test_send_otp_email_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.email_service.get_settings",
        lambda: SimpleNamespace(email_provider="sendgrid"),
    )

    with pytest.raises(RuntimeError, match="Unsupported email provider"):
        asyncio.run(send_otp_email("user@test.com", "000000"))
