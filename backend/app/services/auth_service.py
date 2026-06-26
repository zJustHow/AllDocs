from __future__ import annotations

import uuid
import re
from datetime import UTC, datetime

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.models import Document, DocumentStatus, RefreshToken, User, UserIdentity, UserRole
from app.services.auth_tokens import (
    create_access_token,
    create_refresh_token_value,
    hash_refresh_token,
    refresh_token_expires_at,
)

IDENTITY_EMAIL = "email"
IDENTITY_PHONE = "phone"
IDENTITY_WECHAT = "wechat"
BIND_PROVIDERS = frozenset({IDENTITY_EMAIL, IDENTITY_PHONE, IDENTITY_WECHAT})
MIN_PASSWORD_LEN = 8
_PHONE_DIGITS = re.compile(r"\D+")


class AuthError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters")


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def find_email_identity(db: AsyncSession, email: str) -> UserIdentity | None:
    return await find_identity(db, IDENTITY_EMAIL, normalize_email(email))


async def find_identity(
    db: AsyncSession,
    provider: str,
    provider_uid: str,
) -> UserIdentity | None:
    result = await db.execute(
        select(UserIdentity)
        .options(selectinload(UserIdentity.user))
        .where(UserIdentity.provider == provider, UserIdentity.provider_uid == provider_uid)
    )
    return result.scalar_one_or_none()


def normalize_phone(phone: str) -> str:
    digits = _PHONE_DIGITS.sub("", phone.strip())
    if digits.startswith("86") and len(digits) == 13:
        return f"+{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+86{digits}"
    raise AuthError("Invalid phone number")


async def login_or_register_with_phone(
    db: AsyncSession,
    phone: str,
) -> tuple[User, str, str]:
    identity = await find_identity(db, IDENTITY_PHONE, phone)
    if identity:
        if not identity.user.is_active:
            raise AuthError("Account disabled", status_code=403)
        return identity.user, *await issue_tokens(db, identity.user)

    user = User(role=UserRole.user, display_name=f"用户{phone[-4:]}")
    db.add(user)
    await db.flush()
    db.add(
        UserIdentity(
            user_id=user.id,
            provider=IDENTITY_PHONE,
            provider_uid=phone,
            verified=True,
        )
    )
    await db.flush()
    return user, *await issue_tokens(db, user)


async def login_or_register_with_wechat(
    db: AsyncSession,
    *,
    openid: str,
    unionid: str | None = None,
    nickname: str | None = None,
    avatar_url: str | None = None,
) -> tuple[User, str, str]:
    identity = await find_identity(db, IDENTITY_WECHAT, openid)
    if identity:
        if not identity.user.is_active:
            raise AuthError("Account disabled", status_code=403)
        if nickname and not identity.user.display_name:
            identity.user.display_name = nickname
        extra = dict(identity.extra or {})
        if unionid:
            extra["unionid"] = unionid
        if avatar_url:
            extra["avatar_url"] = avatar_url
        identity.extra = extra or None
        return identity.user, *await issue_tokens(db, identity.user)

    user = User(role=UserRole.user, display_name=nickname or "WeChat User")
    db.add(user)
    await db.flush()
    extra: dict[str, str] = {}
    if unionid:
        extra["unionid"] = unionid
    if avatar_url:
        extra["avatar_url"] = avatar_url
    db.add(
        UserIdentity(
            user_id=user.id,
            provider=IDENTITY_WECHAT,
            provider_uid=openid,
            verified=True,
            extra=extra or None,
        )
    )
    await db.flush()
    return user, *await issue_tokens(db, user)


async def register_with_email(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
    role: UserRole = UserRole.user,
) -> tuple[User, str, str]:
    validate_password(password)
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise AuthError("Invalid email address")

    existing = await find_email_identity(db, normalized)
    if existing:
        raise AuthError("Email already registered", status_code=409)

    user = User(
        role=role,
        display_name=display_name or normalized.split("@", 1)[0],
    )
    db.add(user)
    await db.flush()

    identity = UserIdentity(
        user_id=user.id,
        provider=IDENTITY_EMAIL,
        provider_uid=normalized,
        credential_hash=hash_password(password),
        verified=True,
    )
    db.add(identity)
    await db.flush()
    return user, *await issue_tokens(db, user)


async def login_with_email(
    db: AsyncSession,
    *,
    email: str,
    password: str,
) -> tuple[User, str, str]:
    identity = await find_email_identity(db, email)
    if not identity or not identity.credential_hash:
        raise AuthError("Invalid email or password", status_code=401)
    if not identity.user.is_active:
        raise AuthError("Account disabled", status_code=403)
    if not verify_password(password, identity.credential_hash):
        raise AuthError("Invalid email or password", status_code=401)
    return identity.user, *await issue_tokens(db, identity.user)


async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access_token = create_access_token(user_id=user.id, role=user.role)
    refresh_value = create_refresh_token_value()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_value),
            expires_at=refresh_token_expires_at(),
        )
    )
    await db.flush()
    return access_token, refresh_value


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> tuple[User, str, str]:
    token_hash = hash_refresh_token(refresh_token)
    result = await db.execute(
        select(RefreshToken)
        .options(selectinload(RefreshToken.user))
        .where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    if not stored:
        raise AuthError("Invalid refresh token", status_code=401)

    now = datetime.now(UTC)
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        await db.delete(stored)
        await db.flush()
        raise AuthError("Refresh token expired", status_code=401)

    user = stored.user
    if not user.is_active:
        raise AuthError("Account disabled", status_code=403)

    await db.delete(stored)
    await db.flush()
    return user, *await issue_tokens(db, user)


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    token_hash = hash_refresh_token(refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    stored = result.scalar_one_or_none()
    if stored:
        await db.delete(stored)


async def resolve_chat_doc_ids(
    db: AsyncSession,
    user: User,
    requested_doc_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    del user, requested_doc_ids
    result = await db.execute(
        select(Document.id)
        .where(
            Document.status == DocumentStatus.ready,
            Document.chat_enabled.is_(True),
        )
        .order_by(Document.created_at)
    )
    return list(result.scalars().all())


async def ensure_bootstrap_admin(db: AsyncSession) -> None:
    settings = get_settings()
    email = normalize_email(settings.bootstrap_admin_email)
    password = settings.bootstrap_admin_password
    if not email or not password:
        return

    existing = await find_email_identity(db, email)
    if existing:
        if existing.user.role != UserRole.admin:
            existing.user.role = UserRole.admin
        return

    await register_with_email(
        db,
        email=email,
        password=password,
        display_name="Admin",
        role=UserRole.admin,
    )


def user_email(identity: UserIdentity | None) -> str | None:
    if identity and identity.provider == IDENTITY_EMAIL:
        return identity.provider_uid
    return None


def user_phone(identity: UserIdentity | None) -> str | None:
    if identity and identity.provider == IDENTITY_PHONE:
        return identity.provider_uid
    return None


async def user_has_wechat(db: AsyncSession, user_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(UserIdentity.id).where(
            UserIdentity.user_id == user_id,
            UserIdentity.provider == IDENTITY_WECHAT,
        )
    )
    return result.scalar_one_or_none() is not None


async def bind_phone_to_user(db: AsyncSession, user: User, phone: str) -> User:
    existing = await find_identity(db, IDENTITY_PHONE, phone)
    if existing:
        if existing.user_id == user.id:
            return user
        raise AuthError("Phone already bound to another account", status_code=409)
    db.add(
        UserIdentity(
            user_id=user.id,
            provider=IDENTITY_PHONE,
            provider_uid=phone,
            verified=True,
        )
    )
    await db.flush()
    return user


async def bind_email_to_user(
    db: AsyncSession,
    user: User,
    *,
    email: str,
    password: str,
) -> User:
    validate_password(password)
    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise AuthError("Invalid email address")

    existing = await find_identity(db, IDENTITY_EMAIL, normalized)
    if existing:
        if existing.user_id == user.id:
            return user
        raise AuthError("Email already bound to another account", status_code=409)

    db.add(
        UserIdentity(
            user_id=user.id,
            provider=IDENTITY_EMAIL,
            provider_uid=normalized,
            credential_hash=hash_password(password),
            verified=True,
        )
    )
    await db.flush()
    return user


async def bind_wechat_to_user(
    db: AsyncSession,
    user: User,
    *,
    openid: str,
    unionid: str | None = None,
    nickname: str | None = None,
    avatar_url: str | None = None,
) -> User:
    existing = await find_identity(db, IDENTITY_WECHAT, openid)
    if existing:
        if existing.user_id == user.id:
            return user
        raise AuthError("WeChat already bound to another account", status_code=409)

    extra: dict[str, str] = {}
    if unionid:
        extra["unionid"] = unionid
    if avatar_url:
        extra["avatar_url"] = avatar_url

    db.add(
        UserIdentity(
            user_id=user.id,
            provider=IDENTITY_WECHAT,
            provider_uid=openid,
            verified=True,
            extra=extra or None,
        )
    )
    if nickname and not user.display_name:
        user.display_name = nickname
    await db.flush()
    return user


async def unbind_identity(db: AsyncSession, user: User, provider: str) -> User:
    if provider not in BIND_PROVIDERS:
        raise AuthError("Invalid provider", status_code=400)

    result = await db.execute(select(UserIdentity).where(UserIdentity.user_id == user.id))
    identities = list(result.scalars().all())
    matches = [identity for identity in identities if identity.provider == provider]
    if not matches:
        raise AuthError("Login method not bound", status_code=404)
    if len(identities) <= 1:
        raise AuthError("Cannot unbind the only login method", status_code=400)

    for identity in matches:
        await db.delete(identity)
    await db.flush()
    return user
