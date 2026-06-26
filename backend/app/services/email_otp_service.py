from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import OtpChallenge
from app.services.auth_service import (
    AuthError,
    find_email_identity,
    normalize_email,
    register_with_email,
)
from app.services.email_service import send_otp_email
from app.services.sms_service import generate_otp_code, hash_otp_code


async def send_register_email_otp(db: AsyncSession, email: str) -> None:
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise AuthError("Invalid email address")

    existing = await find_email_identity(db, normalized)
    if existing:
        raise AuthError("Email already registered", status_code=409)

    settings = get_settings()
    now = datetime.now(UTC)

    recent = await db.execute(
        select(OtpChallenge)
        .where(OtpChallenge.email == normalized)
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    )
    latest = recent.scalar_one_or_none()
    if latest:
        created_at = latest.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if (now - created_at).total_seconds() < settings.email_otp_resend_seconds:
            raise AuthError("Please wait before requesting another code", status_code=429)

    await db.execute(delete(OtpChallenge).where(OtpChallenge.email == normalized))

    code = generate_otp_code()
    challenge = OtpChallenge(
        email=normalized,
        phone=None,
        code_hash=hash_otp_code(code),
        expires_at=now + timedelta(seconds=settings.email_otp_ttl_seconds),
    )
    db.add(challenge)
    await db.flush()
    await send_otp_email(normalized, code)


async def verify_register_email_otp(
    db: AsyncSession,
    email: str,
    code: str,
    *,
    password: str,
    display_name: str | None = None,
):
    normalized = await consume_email_otp(db, email, code)

    existing = await find_email_identity(db, normalized)
    if existing:
        raise AuthError("Email already registered", status_code=409)

    return await register_with_email(
        db,
        email=normalized,
        password=password,
        display_name=display_name,
    )


async def consume_email_otp(db: AsyncSession, email: str, code: str) -> str:
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise AuthError("Invalid email address")

    settings = get_settings()
    now = datetime.now(UTC)

    result = await db.execute(
        select(OtpChallenge)
        .where(OtpChallenge.email == normalized)
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise AuthError("Verification code expired or not found", status_code=401)

    expires_at = challenge.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        await db.delete(challenge)
        await db.flush()
        raise AuthError("Verification code expired", status_code=401)

    if challenge.attempts >= settings.email_otp_max_attempts:
        await db.delete(challenge)
        await db.flush()
        raise AuthError("Too many invalid attempts", status_code=429)

    if hash_otp_code(code) != challenge.code_hash:
        challenge.attempts += 1
        await db.flush()
        raise AuthError("Invalid verification code", status_code=401)

    await db.delete(challenge)
    await db.flush()
    return normalized
