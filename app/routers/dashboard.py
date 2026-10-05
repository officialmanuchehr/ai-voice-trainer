from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.analytics import build_dashboard, session_rows
from app.database import SessionLocal
from app.models import Team, User
from app.security import AGGREGATE_ONLY_ROLES, DASHBOARD_ROLES, require_roles

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


@router.get("/managers/{user_id}/sessions")
async def manager_sessions(user_id: str, user: User = Depends(require_roles("sales_lead", "admin"))):
    async with SessionLocal() as db:
        target = await db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="пользователь не найден")
        if user.role == "sales_lead" and (user.team_id is None or target.team_id != user.team_id):
            raise HTTPException(status_code=403, detail="менеджер не из вашей команды")
        return {"user": {"id": target.id, "full_name": target.full_name or target.username}, "sessions": await session_rows(db, [target.id])}
