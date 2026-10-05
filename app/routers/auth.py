from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.audit import audit
from app.config import settings
from app.database import SessionLocal
from app.models import Team, User
from app.security import (
    COOKIE_NAME,
    CONTENT_VIEW_ROLES,
    DASHBOARD_ROLES,
    TRAINEE_ROLES,
    get_current_user,
    make_token,
    user_public,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == body.username.strip()))
        if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="неверный логин или пароль")
        audit(db, user, "auth.login", "user", user.id)
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
