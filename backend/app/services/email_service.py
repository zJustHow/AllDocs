from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_otp_email(email: str, code: str) -> None:
    settings = get_settings()
    provider = settings.email_provider.strip().lower()
    if provider == "console":
        logger.info("Email OTP for %s: %s", email, code)
        return
    if provider == "smtp":
        await _send_smtp_email(email, code)
        return
    raise RuntimeError(f"Unsupported email provider: {settings.email_provider}")


async def _send_smtp_email(email: str, code: str) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from:
        raise RuntimeError("SMTP host and from address are required for email OTP")

    subject = "AllDocs verification code"
    body = (
        f"Your verification code is {code}.\n\n"
        f"It expires in {settings.email_otp_ttl_seconds // 60} minutes."
    )
    await asyncio.to_thread(_send_smtp_sync, email, subject, body)


def _send_smtp_sync(to_email: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message.set_content(body)

    if settings.smtp_use_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
            client.starttls()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password)
            client.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)
