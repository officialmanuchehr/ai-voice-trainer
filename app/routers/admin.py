"""Admin panel API (PRD §12–13): scenarios and knowledge base with versions
and statuses, users and teams, audit journal.

Approved and published versions are never edited in place — an edit creates a
new draft version, so every session stays tied to the exact content it ran on.
"""

import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app.audit import audit
from app.content import (
    DIFFICULTIES,
    TOPICS,
    kb_review_blockers,
    kb_review_message,
    published_kb,
    require_transition,
    validate_kb_content,
    validate_scenario_content,
)
from app.database import SessionLocal
from app.models import CONTENT_STATUSES, AuditLog, KnowledgeBase, Product, Scenario, ScenarioVersion, Team, User
from app.security import (
    CONTENT_VIEW_ROLES,
    KB_APPROVE_ROLES,
    KB_EDIT_ROLES,
    KB_PUBLISH_ROLES,
    ROLES,
    SCENARIO_APPROVE_ROLES,
    SCENARIO_EDIT_ROLES,
    SCENARIO_PUBLISH_ROLES,
    hash_password,
    require_roles,
    user_public,
)
from app.seed_loader import list_rubrics, sync_published_copy

router = APIRouter(prefix="/admin", tags=["admin"])

_PRODUCT_ID_RE = re.compile(r"[a-z0-9_]{2,40}")
_content_viewer = require_roles(*CONTENT_VIEW_ROLES)
_admin = require_roles("admin")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/meta")
async def meta(user: User = Depends(_content_viewer)):
    async with SessionLocal() as db:
        products = (await db.execute(select(Product).order_by(Product.name))).scalars().all()
        teams = (await db.execute(select(Team).order_by(Team.name))).scalars().all()
    return {
        "products": [{"id": p.id, "name": p.name} for p in products],
        "teams": [{"id": t.id, "name": t.name} for t in teams],
        "roles": ROLES,
        "statuses": CONTENT_STATUSES,
        "difficulties": DIFFICULTIES,
        "topics": TOPICS,
        "rubrics": [
            {"id": r["id"], "title": r["title"], "criteria": [{"id": c["id"], "name": c["name"], "weight": c["weight"]} for c in r["criteria"]]}
            for r in list_rubrics()
        ],
        "permissions": {
            "scenario_edit": user.role in SCENARIO_EDIT_ROLES,
            "scenario_approve": user.role in SCENARIO_APPROVE_ROLES,
            "scenario_publish": user.role in SCENARIO_PUBLISH_ROLES,
            "kb_edit": user.role in KB_EDIT_ROLES,
            "kb_approve": user.role in KB_APPROVE_ROLES,
            "kb_publish": user.role in KB_PUBLISH_ROLES,
        },
    }


# ---------------------------------------------------------------- scenarios


def _version_meta(v: ScenarioVersion | KnowledgeBase) -> dict:
    return {
        "version": v.version,
        "status": v.status,
        "author": v.author,
        "created_at": _iso(v.created_at),
        "updated_at": _iso(v.updated_at),
        "approved_by": v.approved_by,
        "published_at": _iso(v.published_at),
    }


@router.get("/scenarios")
async def list_scenarios(user: User = Depends(_content_viewer)):
    async with SessionLocal() as db:
        scenarios = (await db.execute(select(Scenario))).scalars().all()
        versions = (await db.execute(select(ScenarioVersion).order_by(ScenarioVersion.version))).scalars().all()
    by_scenario: dict[str, list[ScenarioVersion]] = {}
    for v in versions:
        by_scenario.setdefault(v.scenario_id, []).append(v)
    items = []
    for s in scenarios:
        own = by_scenario.get(s.id, [])
        latest = own[-1].data if own else {}
        items.append(
            {
                "id": s.id,
                "title": latest.get("title") or s.title or s.id,
                "product_id": latest.get("product_id", s.product_id),
                "difficulty": latest.get("difficulty", s.difficulty),
                "topics": latest.get("topics", []),
                "published_version": s.published_version,
                "versions": [_version_meta(v) for v in own],
            }
        )
    items.sort(key=lambda i: (i["product_id"], i["title"]))
    return items


@router.get("/scenarios/{scenario_id}/versions/{version}")
async def get_scenario_version(scenario_id: str, version: int, user: User = Depends(_content_viewer)):
    async with SessionLocal() as db:
        v = await _scenario_version(db, scenario_id, version)
    return {**_version_meta(v), "scenario_id": scenario_id, "data": v.data}


async def _scenario_version(db, scenario_id: str, version: int) -> ScenarioVersion:
    v = await db.scalar(
        select(ScenarioVersion).where(ScenarioVersion.scenario_id == scenario_id, ScenarioVersion.version == version)
    )
    if v is None:
        raise HTTPException(status_code=404, detail="версия сценария не найдена")
    return v


async def _product_ids(db) -> set[str]:
    return set((await db.execute(select(Product.id))).scalars())


class ScenarioBody(BaseModel):
    data: dict


@router.post("/scenarios")
async def create_scenario(body: ScenarioBody, user: User = Depends(require_roles(*SCENARIO_EDIT_ROLES))):
    async with SessionLocal() as db:
        content = validate_scenario_content(body.data, await _product_ids(db))
        slug = re.sub(r"[^a-z0-9_]", "", content["product_id"].lower())
        scenario_id = f"scn_{slug}_{content['difficulty']}_{secrets.token_hex(3)}"
        db.add(
            Scenario(
                id=scenario_id,
                product_id=content["product_id"],
                client_profile=content["client_profile"],
                difficulty=content["difficulty"],
                goal=content["goal"],
                rubric_id=content["rubric_id"],
                title=content["title"],
            )
        )
        await db.flush()
        db.add(ScenarioVersion(scenario_id=scenario_id, version=1, status="draft", data=content, author=user.username))
        audit(db, user, "scenario.create", "scenario", scenario_id, {"version": 1, "title": content["title"]})
        await db.commit()
    return {"id": scenario_id, "version": 1}


@router.put("/scenarios/{scenario_id}")
async def edit_scenario(scenario_id: str, body: ScenarioBody, user: User = Depends(require_roles(*SCENARIO_EDIT_ROLES))):
    """Edits the latest version if it is still a draft; otherwise starts a new
    draft version. The published version keeps serving managers meanwhile."""
    async with SessionLocal() as db:
        if await db.get(Scenario, scenario_id) is None:
            raise HTTPException(status_code=404, detail="сценарий не найден")
        content = validate_scenario_content(body.data, await _product_ids(db))
        latest = await db.scalar(
            select(ScenarioVersion)
            .where(ScenarioVersion.scenario_id == scenario_id)
            .order_by(ScenarioVersion.version.desc())
        )
        if latest is not None and latest.status == "draft":
            latest.data = content
            latest.author = user.username
            latest.updated_at = _now()
            version = latest.version
            action = "scenario.edit_draft"
        else:
            version = (latest.version if latest else 0) + 1
            db.add(ScenarioVersion(scenario_id=scenario_id, version=version, status="draft", data=content, author=user.username))
            action = "scenario.new_version"
        audit(db, user, action, "scenario", scenario_id, {"version": version, "title": content["title"]})
        await db.commit()
    return {"id": scenario_id, "version": version}


class StatusBody(BaseModel):
    status: str


def _review_conflict(code: str, detail: str, blockers: list[dict]) -> JSONResponse:
    """409 for content that still holds unreviewed placeholders. Returned
    before any change is made, so the version keeps its current status."""
    return JSONResponse(status_code=409, content={"detail": detail, "code": code, "unreviewed": blockers})


@router.post("/scenarios/{scenario_id}/versions/{version}/status")
async def set_scenario_status(scenario_id: str, version: int, body: StatusBody, user: User = Depends(_content_viewer)):
    async with SessionLocal() as db:
        scenario = await db.get(Scenario, scenario_id)
        v = await _scenario_version(db, scenario_id, version)
        previous = v.status
        require_transition(user, v, body.status)
        if body.status == "published":
            kb = await published_kb(db, v.data["product_id"])
            if kb is None:
                raise HTTPException(status_code=409, detail="сначала опубликуйте базу знаний этого продукта")
            blockers = kb_review_blockers(kb.data)
            if blockers:
                return _review_conflict(
                    "kb_not_clean",
                    kb_review_message(f"Опубликованная база знаний продукта (v{kb.version}) не проверена", blockers),
                    blockers,
                )
            others = await db.execute(
                select(ScenarioVersion).where(
                    ScenarioVersion.scenario_id == scenario_id,
                    ScenarioVersion.status == "published",
                    ScenarioVersion.version != version,
                )
            )
            for other in others.scalars():
                other.status = "archived"
            v.published_at = _now()
            sync_published_copy(scenario, v)
        elif body.status == "approved":
            v.approved_by = user.username
        elif body.status == "archived" and scenario.published_version == version:
            scenario.published_version = None
        v.status = body.status
        audit(db, user, "scenario.status", "scenario", scenario_id, {"version": version, "from": previous, "to": body.status})
        await db.commit()
    return {"id": scenario_id, "version": version, "status": body.status}


# ----------------------------------------------------------- knowledge base


@router.get("/kb")
async def list_kb(user: User = Depends(_content_viewer)):
    async with SessionLocal() as db:
        products = (await db.execute(select(Product).order_by(Product.name))).scalars().all()
        versions = (await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.id))).scalars().all()
    by_product: dict[str, list[KnowledgeBase]] = {}
    for v in versions:
        by_product.setdefault(v.product_id, []).append(v)
    return [
        {
            "product_id": p.id,
            "name": p.name,
            "segment": p.segment,
            "versions": [{**_version_meta(v), "notes": v.notes} for v in by_product.get(p.id, [])],
        }
        for p in products
    ]


async def _kb_version(db, product_id: str, version: str) -> KnowledgeBase:
    kb = await db.scalar(
        select(KnowledgeBase).where(KnowledgeBase.product_id == product_id, KnowledgeBase.version == version)
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="версия базы знаний не найдена")
    return kb


@router.get("/kb/{product_id}/versions/{version}")
async def get_kb_version(product_id: str, version: str, user: User = Depends(_content_viewer)):
    async with SessionLocal() as db:
        kb = await _kb_version(db, product_id, version)
    return {**_version_meta(kb), "product_id": product_id, "notes": kb.notes, "data": kb.data}


class NewKbVersion(BaseModel):
    version: str
    data: dict | None = None
    base_version: str | None = None
    notes: str | None = None


@router.post("/kb/{product_id}/versions")
async def create_kb_version(product_id: str, body: NewKbVersion, user: User = Depends(require_roles(*KB_EDIT_ROLES))):
    """New draft KB version. Copies `base_version` (or the latest version)
    unless `data` is given; with `data` and an unknown product_id this also
    creates the product."""
    version = body.version.strip()
    if not version:
        raise HTTPException(status_code=422, detail="укажите номер версии")
    if not _PRODUCT_ID_RE.fullmatch(product_id):
        raise HTTPException(status_code=422, detail="id продукта: 2–40 символов a-z, 0-9, _")
    async with SessionLocal() as db:
        product = await db.get(Product, product_id)
        exists = await db.scalar(
            select(KnowledgeBase).where(KnowledgeBase.product_id == product_id, KnowledgeBase.version == version)
        )
        if exists is not None:
            raise HTTPException(status_code=409, detail="такая версия уже есть")
        if body.data is not None:
            data = validate_kb_content(body.data, product_id)
        elif product is None:
            raise HTTPException(status_code=422, detail="для нового продукта нужно передать data")
        else:
            base_query = select(KnowledgeBase).where(KnowledgeBase.product_id == product_id)
            if body.base_version:
                base_query = base_query.where(KnowledgeBase.version == body.base_version)
            base = await db.scalar(base_query.order_by(KnowledgeBase.id.desc()))
            if base is None:
                raise HTTPException(status_code=404, detail="базовая версия не найдена")
            data = base.data
        if product is None:
            db.add(Product(id=product_id, name=data["name"], segment=data["segment"]))
            await db.flush()
        db.add(
            KnowledgeBase(
                product_id=product_id, version=version, data=data, status="draft", author=user.username, notes=body.notes
            )
        )
        audit(db, user, "kb.new_version", "knowledge_base", f"{product_id}@{version}", {"base_version": body.base_version})
        await db.commit()
    return {"product_id": product_id, "version": version}


class KbEdit(BaseModel):
    data: dict
    notes: str | None = None


@router.put("/kb/{product_id}/versions/{version}")
async def edit_kb_version(product_id: str, version: str, body: KbEdit, user: User = Depends(require_roles(*KB_EDIT_ROLES))):
    async with SessionLocal() as db:
        kb = await _kb_version(db, product_id, version)
        if kb.status != "draft":
            raise HTTPException(status_code=409, detail="редактировать можно только черновик — создайте новую версию")
        kb.data = validate_kb_content(body.data, product_id)
        kb.notes = body.notes
        kb.author = user.username
        kb.updated_at = _now()
        audit(db, user, "kb.edit_draft", "knowledge_base", f"{product_id}@{version}")
        await db.commit()
    return {"product_id": product_id, "version": version}


@router.post("/kb/{product_id}/versions/{version}/status")
async def set_kb_status(product_id: str, version: str, body: StatusBody, user: User = Depends(_content_viewer)):
    async with SessionLocal() as db:
        kb = await _kb_version(db, product_id, version)
        previous = kb.status
        require_transition(user, kb, body.status)
        if body.status in ("approved", "published"):
            blockers = kb_review_blockers(kb.data)
            if blockers:
                return _review_conflict(
                    "kb_unreviewed", kb_review_message("Эту версию базы знаний нельзя утвердить или опубликовать", blockers), blockers
                )
        if body.status == "published":
            others = await db.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.product_id == product_id,
                    KnowledgeBase.status == "published",
                    KnowledgeBase.id != kb.id,
                )
            )
            for other in others.scalars():
                other.status = "archived"
            kb.published_at = _now()
            product = await db.get(Product, product_id)
            product.name = kb.data["name"]
            product.segment = kb.data["segment"]
        elif body.status == "approved":
            kb.approved_by = user.username
        kb.status = body.status
        audit(
            db, user, "kb.status", "knowledge_base", f"{product_id}@{version}", {"from": previous, "to": body.status}
        )
        await db.commit()
    return {"product_id": product_id, "version": version, "status": body.status}


# ------------------------------------------------------------ users, teams


@router.get("/users")
async def list_users(user: User = Depends(_admin)):
    async with SessionLocal() as db:
        users = (await db.execute(select(User).order_by(User.role, User.username))).scalars().all()
    return [{**user_public(u), "created_at": _iso(u.created_at)} for u in users]


class NewUser(BaseModel):
    username: str
    full_name: str
    role: str
    password: str
    team_id: int | None = None


def _check_user_fields(role: str, password: str | None) -> None:
    if role not in ROLES:
        raise HTTPException(status_code=422, detail="неизвестная роль")
    if password is not None and len(password) < 8:
        raise HTTPException(status_code=422, detail="пароль — минимум 8 символов")


@router.post("/users")
async def create_user(body: NewUser, user: User = Depends(_admin)):
    _check_user_fields(body.role, body.password)
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="укажите логин")
    async with SessionLocal() as db:
        if await db.scalar(select(User).where(User.username == username)) is not None:
            raise HTTPException(status_code=409, detail="такой логин уже есть")
        new_user = User(
            username=username,
            full_name=body.full_name.strip(),
            role=body.role,
            team_id=body.team_id,
            password_hash=hash_password(body.password),
        )
        db.add(new_user)
        await db.flush()
        audit(db, user, "user.create", "user", new_user.id, {"username": username, "role": body.role, "team_id": body.team_id})
        await db.commit()
        return user_public(new_user)


class EditUser(BaseModel):
    full_name: str
    role: str
    team_id: int | None = None
    is_active: bool = True
    password: str | None = None


@router.put("/users/{user_id}")
async def edit_user(user_id: str, body: EditUser, user: User = Depends(_admin)):
    password = body.password or None
    _check_user_fields(body.role, password)
    if user_id == user.id and (not body.is_active or body.role != "admin"):
        raise HTTPException(status_code=400, detail="нельзя отключить себя или снять с себя роль администратора")
    async with SessionLocal() as db:
        target = await db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="пользователь не найден")
        changes = {
            k: v
            for k, v in {"role": body.role, "team_id": body.team_id, "is_active": body.is_active}.items()
            if getattr(target, k) != v
        }
        target.full_name = body.full_name.strip()
        target.role = body.role
        target.team_id = body.team_id
        target.is_active = body.is_active
        if password:
            target.password_hash = hash_password(password)
            changes["password"] = "reset"
        audit(db, user, "user.edit", "user", target.id, {"username": target.username, **changes})
        await db.commit()
        return user_public(target)


@router.get("/teams")
async def list_teams(user: User = Depends(_admin)):
    async with SessionLocal() as db:
        teams = (await db.execute(select(Team).order_by(Team.name))).scalars().all()
        counts = dict(
            (await db.execute(select(User.team_id, func.count()).group_by(User.team_id))).all()
        )
    return [{"id": t.id, "name": t.name, "members": counts.get(t.id, 0)} for t in teams]


class NewTeam(BaseModel):
    name: str


@router.post("/teams")
async def create_team(body: NewTeam, user: User = Depends(_admin)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="укажите название")
    async with SessionLocal() as db:
        if await db.scalar(select(Team).where(Team.name == name)) is not None:
            raise HTTPException(status_code=409, detail="такая команда уже есть")
        team = Team(name=name)
        db.add(team)
        await db.flush()
        audit(db, user, "team.create", "team", str(team.id), {"name": name})
        await db.commit()
        return {"id": team.id, "name": team.name}


# -------------------------------------------------------------------- audit


@router.get("/audit")
async def list_audit(limit: int = 200, entity_type: str | None = None, user: User = Depends(require_roles("admin", "compliance"))):
    async with SessionLocal() as db:
        query = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 1000))
        if entity_type:
            query = query.where(AuditLog.entity_type == entity_type)
        rows = (await db.execute(query)).scalars().all()
    return [
        {
            "id": r.id,
            "ts": _iso(r.ts),
            "actor": r.actor_username,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "details": r.details,
        }
        for r in rows
    ]
