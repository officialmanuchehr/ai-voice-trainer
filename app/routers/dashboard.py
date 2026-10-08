from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.analytics import build_dashboard, build_progress, session_rows
from app.database import SessionLocal
from app.models import Team, User
from app.security import AGGREGATE_ONLY_ROLES, DASHBOARD_ROLES, lead_may_view, require_roles

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/data")
async def dashboard(
    days: int | None = 30,
    product_id: str | None = None,
    team_id: int | None = None,
    user: User = Depends(require_roles(*DASHBOARD_ROLES)),
):
    """Sales leads always see exactly their own team, with names. Admins may
    pick any team. Training, product and compliance see aggregates across all
    teams without individual managers (PRD §14)."""
    if user.role == "sales_lead":
        if user.team_id is None:
            raise HTTPException(status_code=409, detail="руководитель не привязан к команде — обратитесь к администратору")
        team_id = user.team_id
    named = user.role not in AGGREGATE_ONLY_ROLES
    async with SessionLocal() as db:
        data = await build_dashboard(db, user, days if days and days > 0 else None, product_id or None, team_id, named)
        teams = (await db.execute(select(Team).order_by(Team.name))).scalars().all()
    data["team_id"] = team_id
    data["teams"] = [{"id": t.id, "name": t.name} for t in teams] if user.role != "sales_lead" else []
    return data


async def _managed_user(db, user_id: str, viewer: User) -> User:
    """The drill-down target. Admin: any user. Sales lead: only a manager on
    the lead's own team (lead_may_view)."""
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="пользователь не найден")
    if viewer.role == "sales_lead" and not lead_may_view(viewer, target):
        raise HTTPException(status_code=403, detail="менеджер не из вашей команды")
    return target


def _identity(target: User) -> dict:
    return {"id": target.id, "full_name": target.full_name or target.username}


@router.get("/managers/{user_id}/sessions")
async def manager_sessions(user_id: str, user: User = Depends(require_roles("sales_lead", "admin"))):
    async with SessionLocal() as db:
        target = await _managed_user(db, user_id, user)
        return {"user": _identity(target), "sessions": await session_rows(db, [target.id])}


@router.get("/managers/{user_id}/progress")
async def manager_progress(user_id: str, user: User = Depends(require_roles("sales_lead", "admin"))):
    """One manager's training progress for their lead (or an admin): exactly
    the /me/progress shape (analytics.build_progress, unchanged) plus a
    minimal identity. Read-only; no transcripts or hidden fields."""
    async with SessionLocal() as db:
        target = await _managed_user(db, user_id, user)
        return {"user": _identity(target), **await build_progress(db, target.id)}
