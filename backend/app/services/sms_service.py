from __future__ import annotations

import hashlib
import logging
import secrets

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_otp_sms(phone: str, code: str) -> None:
    settings = get_settings()
    provider = settings.sms_provider.strip().lower()
    if provider == "console":
        logger.info("OTP for %s: %s", phone, code)
        return
    if provider == "aliyun":
        await _send_aliyun_sms(phone, code)
        return
    raise RuntimeError(f"Unsupported SMS provider: {settings.sms_provider}")


async def _send_aliyun_sms(phone: str, code: str) -> None:
    settings = get_settings()
    if not all(
        [
            settings.aliyun_sms_access_key_id,
            settings.aliyun_sms_access_key_secret,
            settings.aliyun_sms_sign_name,
            settings.aliyun_sms_template_code,
        ]
    ):
        raise RuntimeError("Aliyun SMS credentials are not configured")

    from app.services.aliyun_sms import send_aliyun_sms

    await send_aliyun_sms(phone, code)


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp_code(code: str) -> str:
    settings = get_settings()
    payload = f"{settings.jwt_secret}:{code.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
