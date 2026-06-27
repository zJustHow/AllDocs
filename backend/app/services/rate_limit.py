from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

from app.config import get_settings

_lock = Lock()
_attempts: dict[str, list[float]] = defaultdict(list)


def _client_key(request: Request, bucket: str) -> str:
    client = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client = forwarded.split(",")[0].strip()
    return f"{bucket}:{client}"


def check_rate_limit(key: str, *, max_attempts: int, window_seconds: int) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        attempts = [timestamp for timestamp in _attempts[key] if timestamp > cutoff]
        if len(attempts) >= max_attempts:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please try again later.",
            )
        attempts.append(now)
        _attempts[key] = attempts


def enforce_auth_rate_limit(request: Request) -> None:
    settings = get_settings()
    check_rate_limit(
        _client_key(request, "auth"),
        max_attempts=settings.auth_login_rate_limit_attempts,
        window_seconds=settings.auth_login_rate_limit_window_seconds,
    )
