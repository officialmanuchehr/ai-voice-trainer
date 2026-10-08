"""Login throttling, stored in the database (serverless instances share no
memory). Failures are counted per (normalised username, client IP) within a
sliding window; at the limit, further attempts are refused before the
password is even checked, so a throttled response says nothing about whether
the username or password was right.
"""

import hashlib
import hmac
import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import LoginAttempt
from app.security import hash_password, verify_password


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalise_username(username: str) -> str:
    return username.strip().lower()


def client_ip(request: Request) -> str:
    """The configured trusted proxy header if it holds a valid IP, else the
    direct peer. Never an arbitrary client-supplied header."""
    if settings.client_ip_header:
        raw = request.headers.get(settings.client_ip_header, "").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def attempt_key(username: str, ip: str) -> str:
    secret = (settings.secret_key or "dev-only-insecure-secret").encode()
    return hmac.new(secret, f"{normalise_username(username)}|{ip}".encode(), hashlib.sha256).hexdigest()


def _window_start() -> datetime:
    return _now() - timedelta(minutes=settings.login_window_minutes)


async def recent_failures(db: AsyncSession, key: str) -> int:
    return await db.scalar(
        select(func.count()).select_from(LoginAttempt).where(LoginAttempt.key_hash == key, LoginAttempt.created_at >= _window_start())
    )


async def retry_after_seconds(db: AsyncSession, key: str) -> int:
    """Seconds until the oldest failure still counting toward the limit expires."""
    times = (
        await db.execute(
            select(LoginAttempt.created_at)
            .where(LoginAttempt.key_hash == key, LoginAttempt.created_at >= _window_start())
            .order_by(LoginAttempt.created_at.desc())
            .limit(settings.login_max_failures)
        )
    ).scalars().all()
    if not times:
        return 0
    oldest = min(times)
    if oldest.tzinfo is None:  # SQLite returns naive UTC
        oldest = oldest.replace(tzinfo=timezone.utc)
    expires = oldest + timedelta(minutes=settings.login_window_minutes)
    return max(1, int((expires - _now()).total_seconds()) + 1)


async def record_failure(db: AsyncSession, key: str) -> None:
    db.add(LoginAttempt(key_hash=key, created_at=_now()))
    await db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < _window_start()))


async def clear_failures(db: AsyncSession, key: str) -> None:
    await db.execute(delete(LoginAttempt).where(LoginAttempt.key_hash == key))


_dummy_hash: str | None = None


def password_matches(password: str, stored_hash: str | None) -> bool:
    """verify_password, but an unknown user still pays the full PBKDF2 cost so
    response time doesn't reveal whether the username exists."""
    global _dummy_hash
    if stored_hash is None:
        if _dummy_hash is None:
            _dummy_hash = hash_password("dummy-password-for-timing")
        verify_password(password, _dummy_hash)
        return False
    return verify_password(password, stored_hash)
