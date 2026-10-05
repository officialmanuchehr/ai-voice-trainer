from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.audit import audit
from app.config import settings
from app.database import SessionLocal
from app.http_security import request_id_var
from app.login_guard import (
    attempt_key,
    clear_failures,
    client_ip,
    password_matches,
    recent_failures,
    record_failure,
    retry_after_seconds,
)
from app.models import Team, User
from app.security import (
    COOKIE_NAME,
    CONTENT_VIEW_ROLES,
    DASHBOARD_ROLES,
    TRAINEE_ROLES,
    get_current_user,
    make_token,
    user_public,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def _throttled(seconds: int) -> JSONResponse:
    minutes = max(1, -(-seconds // 60))
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(seconds)},
        content={
            "code": "login_throttled",
            "detail": f"Слишком много неудачных попыток входа. Попробуйте снова через {minutes} мин.",
            "request_id": request_id_var.get(),
        },
    )


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    ip = client_ip(request)
    key = attempt_key(body.username, ip)
    async with SessionLocal() as db:
        # Checked before the password, so a throttled answer is the same for
        # right and wrong passwords and for unknown usernames.
        failures = await recent_failures(db, key)
        if failures >= settings.login_max_failures:
            return _throttled(await retry_after_seconds(db, key))

        user = await db.scalar(select(User).where(User.username == body.username.strip()))
        valid = password_matches(body.password, user.password_hash if user else None) and user.is_active
        if not valid:
            await record_failure(db, key)
            # Username only for a real account (a mistyped password in the
            # username field must not end up in the journal); never the password.
            details = {"username": user.username if user else None, "ip": ip}
            audit(db, None, "auth.login_failed", "user", user.id if user else None, details)
            if failures + 1 == settings.login_max_failures:
                audit(db, None, "auth.login_throttled", "user", user.id if user else None, {**details, "failures": failures + 1})
            await db.commit()
            raise HTTPException(status_code=401, detail="неверный логин или пароль")

        await clear_failures(db, key)
        audit(db, user, "auth.login", "user", user.id, {"previous_failures": failures} if failures else None)
        await db.commit()

    response.set_cookie(
        COOKIE_NAME,
        make_token(user.id),
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )
    return user_public(user)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    team_name = None
    if user.team_id is not None:
        async with SessionLocal() as db:
            team = await db.get(Team, user.team_id)
            team_name = team.name if team else None
    return {
        **user_public(user),
        "team_name": team_name,
        "can_train": user.role in TRAINEE_ROLES,
        "can_dashboard": user.role in DASHBOARD_ROLES,
        "can_content": user.role in CONTENT_VIEW_ROLES,
        "can_users": user.role == "admin",
    }
