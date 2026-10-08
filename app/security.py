"""Users, roles and the login cookie.

Stateless signed cookie (no server-side session table) so it works unchanged
on serverless, where each request may hit a fresh worker. The user row is
still re-read on every request, so deactivating a user or changing their role
takes effect immediately. Cookies carry a session revision; password resets
increment it to revoke all previously issued cookies.
"""

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request

from app.config import settings
from app.database import SessionLocal
from app.models import User

COOKIE_NAME = "avt_session"
_PBKDF2_ITERATIONS = 200_000
_DEV_SECRET = "dev-only-insecure-secret"

ROLES = {
    "manager": "Клиентский менеджер",
    "sales_lead": "Руководитель продаж",
    "training": "Команда обучения",
    "product": "Продуктовая команда",
    "compliance": "Комплаенс / контроль качества",
    "admin": "Администратор",
}

# Who may do what (PRD §2, §12, §13). Kept in one place so the API and the
# frontend's role-dependent navigation agree.
TRAINEE_ROLES = {"manager", "sales_lead", "training", "admin"}
DASHBOARD_ROLES = {"sales_lead", "training", "product", "compliance", "admin"}
# These see only aggregates — no manager names, no transcripts (PRD §14).
AGGREGATE_ONLY_ROLES = {"training", "product", "compliance"}
CONTENT_VIEW_ROLES = {"training", "product", "compliance", "admin"}

SCENARIO_EDIT_ROLES = {"training", "admin"}
SCENARIO_APPROVE_ROLES = {"product", "compliance", "admin"}
SCENARIO_PUBLISH_ROLES = {"training", "admin"}

KB_EDIT_ROLES = {"product", "compliance", "admin"}
KB_APPROVE_ROLES = {"compliance", "admin"}
KB_PUBLISH_ROLES = {"product", "admin"}


def lead_may_view(lead: User, target: User | None) -> bool:
    """A sales lead's individual-data scope: users with the manager role on
    the lead's own (current) team. Same-team membership alone is not enough —
    other leads, trainers or admins assigned to the team are outside it."""
    return (
        target is not None
        and lead.team_id is not None
        and target.role == "manager"
        and target.team_id == lead.team_id
    )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


def _secret() -> bytes:
    if settings.secret_key:
        return settings.secret_key.encode()
    if settings.database_url.startswith("sqlite"):
        return _DEV_SECRET.encode()
    raise RuntimeError("SECRET_KEY must be set outside local SQLite development")


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(user_id: str, session_revision: int = 0) -> str:
    expires = int(time.time()) + settings.session_ttl_hours * 3600
    payload = f"{user_id}.{expires}.{session_revision}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> tuple[str, int] | None:
    try:
        parts = token.split(".")
        if len(parts) == 3:  # pre-migration cookies belong to revision zero
            user_id, expires, signature = parts
            revision = 0
        else:
            user_id, expires, raw_revision, signature = parts
            revision = int(raw_revision)
        payload = ".".join(parts[:-1])
        if not hmac.compare_digest(signature, _sign(payload)):
            return None
        if int(expires) < time.time():
            return None
    except (ValueError, TypeError):
        return None
    return user_id, revision


async def get_current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE_NAME)
    identity = read_token(token) if token else None
    if identity is None:
        raise HTTPException(status_code=401, detail="не выполнен вход")
    async with SessionLocal() as db:
        user = await db.get(User, identity[0])
    if user is None or not user.is_active or user.session_revision != identity[1]:
        raise HTTPException(status_code=401, detail="пользователь не найден или отключён")
    return user


def require_roles(*roles: str):
    allowed = set(roles)

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="недостаточно прав")
        return user

    return dependency


def user_public(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "role_name": ROLES.get(user.role, user.role),
        "team_id": user.team_id,
        "is_active": user.is_active,
    }
