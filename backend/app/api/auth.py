from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_deps import get_current_user, get_current_user_flexible
from app.db.models import User, UserIdentity
from app.db.session import get_db
from app.services.auth_service import (
    AuthError,
    bind_email_to_user,
    bind_phone_to_user,
    bind_wechat_to_user,
    login_or_register_with_wechat,
    login_with_email,
    refresh_access_token,
    register_with_email,
    revoke_refresh_token,
    unbind_identity,
    user_email,
    user_has_wechat,
    user_phone,
)
from app.services.auth_tokens import create_oauth_state, parse_oauth_state
from app.services.email_otp_service import send_register_email_otp, verify_register_email_otp
from app.services.otp_service import consume_phone_otp, send_phone_otp, verify_phone_otp
from app.services.wechat_oauth import (
    WeChatOAuthError,
    build_frontend_bind_callback_url,
    build_frontend_callback_url,
    build_wechat_authorize_url,
    exchange_wechat_code,
    fetch_wechat_profile,
    wechat_oauth_enabled,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class EmailRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)


class EmailLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    password: str = Field(min_length=1, max_length=128)


class OtpSendRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)


class OtpVerifyRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=8)


class EmailOtpSendRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)


class EmailOtpRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    code: str = Field(min_length=4, max_length=8)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)


class BindEmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class OtpSendResponse(BaseModel):
    status: str = "sent"


class UserResponse(BaseModel):
    id: str
    role: str
    display_name: str | None
    email: str | None
    phone: str | None
    wechat_bound: bool


def _token_response(access_token: str, refresh_token: str) -> TokenResponse:
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


def _user_response(
    user: User,
    *,
    email: str | None,
    phone: str | None,
    wechat_bound: bool,
) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        role=user.role.value,
        display_name=user.display_name,
        email=email,
        phone=phone,
        wechat_bound=wechat_bound,
    )


async def _profile_payload(db: AsyncSession, user: User) -> UserResponse:
    email, phone = await _primary_identities(db, user)
    wechat_bound = await user_has_wechat(db, user.id)
    return _user_response(user, email=email, phone=phone, wechat_bound=wechat_bound)


async def _primary_identities(db: AsyncSession, user: User) -> tuple[str | None, str | None]:
    result = await db.execute(
        select(UserIdentity).where(
            UserIdentity.user_id == user.id,
            UserIdentity.provider.in_(("email", "phone")),
        )
    )
    email: str | None = None
    phone: str | None = None
    for identity in result.scalars().all():
        if identity.provider == "email":
            email = user_email(identity)
        elif identity.provider == "phone":
            phone = user_phone(identity)
    return email, phone


@router.post("/register/email", response_model=TokenResponse)
async def register_email(
    body: EmailRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        _user, access_token, refresh_token = await register_with_email(
            db,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _token_response(access_token, refresh_token)


@router.post("/register/email-otp/send", response_model=OtpSendResponse)
async def send_register_email_otp_route(
    body: EmailOtpSendRequest,
    db: AsyncSession = Depends(get_db),
) -> OtpSendResponse:
    try:
        await send_register_email_otp(db, body.email)
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return OtpSendResponse()


@router.post("/register/email-otp/verify", response_model=TokenResponse)
async def verify_register_email_otp_route(
    body: EmailOtpRegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        _user, access_token, refresh_token = await verify_register_email_otp(
            db,
            body.email,
            body.code,
            password=body.password,
            display_name=body.display_name,
        )
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _token_response(access_token, refresh_token)


@router.post("/login/email", response_model=TokenResponse)
async def login_email(
    body: EmailLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        _user, access_token, refresh_token = await login_with_email(
            db,
            email=body.email,
            password=body.password,
        )
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _token_response(access_token, refresh_token)


@router.post("/otp/send", response_model=OtpSendResponse)
async def send_otp(
    body: OtpSendRequest,
    db: AsyncSession = Depends(get_db),
) -> OtpSendResponse:
    try:
        await send_phone_otp(db, body.phone)
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return OtpSendResponse()


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp(
    body: OtpVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        _user, access_token, refresh_token = await verify_phone_otp(
            db,
            body.phone,
            body.code,
        )
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _token_response(access_token, refresh_token)


@router.get("/wechat/authorize")
async def wechat_authorize() -> RedirectResponse:
    if not wechat_oauth_enabled():
        raise HTTPException(status_code=503, detail="WeChat OAuth is not configured")
    state = create_oauth_state("wechat")
    return RedirectResponse(build_wechat_authorize_url(state), status_code=302)


@router.get("/wechat/bind/authorize")
async def wechat_bind_authorize(
    user: User = Depends(get_current_user_flexible),
) -> RedirectResponse:
    if not wechat_oauth_enabled():
        raise HTTPException(status_code=503, detail="WeChat OAuth is not configured")
    state = create_oauth_state("wechat", bind_user_id=user.id)
    return RedirectResponse(build_wechat_authorize_url(state), status_code=302)


@router.get("/wechat/callback")
async def wechat_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if not wechat_oauth_enabled():
        raise HTTPException(status_code=503, detail="WeChat OAuth is not configured")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing WeChat OAuth parameters")
    try:
        state_payload = parse_oauth_state(state, "wechat")
        token_payload = await exchange_wechat_code(code)
        openid = str(token_payload["openid"])
        access_token = str(token_payload.get("access_token", ""))
        unionid = token_payload.get("unionid")
        nickname = None
        avatar_url = None
        if access_token:
            profile = await fetch_wechat_profile(access_token, openid)
            nickname = profile.get("nickname")
            avatar_url = profile.get("headimgurl")

        bind_user_id = state_payload.get("bind_user_id")
        if bind_user_id:
            user = await db.get(User, uuid.UUID(str(bind_user_id)))
            if not user:
                raise AuthError("User not found", status_code=404)
            await bind_wechat_to_user(
                db,
                user,
                openid=openid,
                unionid=str(unionid) if unionid else None,
                nickname=str(nickname) if nickname else None,
                avatar_url=str(avatar_url) if avatar_url else None,
            )
            await db.commit()
            return RedirectResponse(
                build_frontend_bind_callback_url(provider="wechat"),
                status_code=302,
            )

        _user, jwt_access, jwt_refresh = await login_or_register_with_wechat(
            db,
            openid=openid,
            unionid=str(unionid) if unionid else None,
            nickname=str(nickname) if nickname else None,
            avatar_url=str(avatar_url) if avatar_url else None,
        )
        await db.commit()
    except (WeChatOAuthError, InvalidTokenError, AuthError) as exc:
        status_code = getattr(exc, "status_code", 400)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return RedirectResponse(
        build_frontend_callback_url(access_token=jwt_access, refresh_token=jwt_refresh),
        status_code=302,
    )


@router.post("/bind/email", response_model=UserResponse)
async def bind_email(
    body: BindEmailRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    try:
        await bind_email_to_user(
            db,
            user,
            email=body.email,
            password=body.password,
        )
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return await _profile_payload(db, user)


@router.post("/bind/otp/send", response_model=OtpSendResponse)
async def bind_send_otp(
    body: OtpSendRequest,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OtpSendResponse:
    try:
        await send_phone_otp(db, body.phone)
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return OtpSendResponse()


@router.post("/bind/otp/verify", response_model=UserResponse)
async def bind_verify_otp(
    body: OtpVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    try:
        phone = await consume_phone_otp(db, body.phone, body.code)
        await bind_phone_to_user(db, user, phone)
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return await _profile_payload(db, user)


@router.delete("/bind/{provider}", response_model=UserResponse)
async def unbind_provider(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    try:
        await unbind_identity(db, user, provider.strip().lower())
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return await _profile_payload(db, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        _user, access_token, refresh_token = await refresh_access_token(db, body.refresh_token)
        await db.commit()
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _token_response(access_token, refresh_token)


@router.post("/logout")
async def logout(
    body: LogoutRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, str]:
    if body.refresh_token:
        await revoke_refresh_token(db, body.refresh_token)
        await db.commit()
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
async def read_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await _profile_payload(db, user)
