from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User, UserRole
from app.db.session import get_db
from app.services.auth_service import get_user_by_id
from app.services.auth_tokens import decode_access_token

_bearer = HTTPBearer(auto_error=False)

_DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _dev_user() -> User:
    return User(
        id=_DEV_USER_ID,
        role=UserRole.admin,
        display_name="Dev",
        is_active=True,
    )


async def _user_from_access_token(token: str, db: AsyncSession) -> User:
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(str(payload["sub"]))
    except (InvalidTokenError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc

    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _extract_bearer_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if get_settings().auth_disabled:
        return _dev_user()

    token = _extract_bearer_token(request, credentials)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await _user_from_access_token(token, db)


async def get_current_user_flexible(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if get_settings().auth_disabled:
        return _dev_user()

    access_token = _extract_bearer_token(request, credentials) or token
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return await _user_from_access_token(access_token, db)


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

