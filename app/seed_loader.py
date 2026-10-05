import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import KnowledgeBase, Product, Scenario, ScenarioVersion, Team, User
from app.security import hash_password

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

# Seed-file bookkeeping keys that are not part of the stored content.
_SEED_ONLY_KEYS = {"seed_status"}


def _load(name: str) -> dict:
    with open(SEED_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def scenario_content(scenario: dict) -> dict:
    """The versioned part of a scenario (what ScenarioVersion.data holds)."""
    return {
        "product_id": scenario["product_id"],
        "title": scenario.get("title") or scenario["id"],
        "difficulty": scenario["difficulty"],
        "goal": scenario["goal"],
        "rubric_id": scenario["rubric_id"],
        "client_profile": scenario["client_profile"],
        "config": scenario.get("config") or {},
    }


def sync_published_copy(scenario: Scenario, version: ScenarioVersion) -> None:
    content = version.data
    scenario.product_id = content["product_id"]
    scenario.title = content.get("title")
    scenario.difficulty = content["difficulty"]
    scenario.goal = content["goal"]
    scenario.rubric_id = content["rubric_id"]
    scenario.client_profile = content["client_profile"]
    scenario.published_version = version.version


async def load_seed(db: AsyncSession) -> None:
    """Bootstraps an empty database and backfills rows added by later schema
    changes. Insert-only: once a product, KB version or scenario exists, the
    database — edited through the admin panel — is the source of truth and the
    seed files never overwrite it."""
    kb_data = _load("knowledge_base.json")
    scenarios_data = _load("scenarios.json")
    kb_version = kb_data["kb_version"]
    now = datetime.now(timezone.utc)

    for product in kb_data["products"]:
        product_id = product["id"]
        status = product.get("seed_status", "published")
        content = {k: v for k, v in product.items() if k not in _SEED_ONLY_KEYS}

        if await db.get(Product, product_id) is None:
            db.add(Product(id=product_id, name=product["name"], segment=product["segment"]))

        existing_kb = await db.scalar(
            select(KnowledgeBase).where(KnowledgeBase.product_id == product_id, KnowledgeBase.version == kb_version)
        )
        if existing_kb is None:
            db.add(
                KnowledgeBase(
                    product_id=product_id,
                    version=kb_version,
                    data=content,
                    status=status,
                    author="seed",
                    published_at=now if status == "published" else None,
                )
            )

    await db.flush()

    for scenario in scenarios_data["scenarios"]:
        status = scenario.get("seed_status", "published")
        content = scenario_content(scenario)

        row = await db.get(Scenario, scenario["id"])
        if row is None:
            row = Scenario(
                id=scenario["id"],
                product_id=content["product_id"],
                client_profile=content["client_profile"],
                difficulty=content["difficulty"],
                goal=content["goal"],
                rubric_id=content["rubric_id"],
                title=content["title"],
            )
            db.add(row)
            await db.flush()

        versions = await db.scalar(
            select(func.count()).select_from(ScenarioVersion).where(ScenarioVersion.scenario_id == row.id)
        )
        if not versions:
            # Also the backfill path for scenarios created before versioning:
            # their sessions (scenario_version NULL) are treated as version 1.
            version = ScenarioVersion(
                scenario_id=row.id,
                version=1,
                status=status,
                data=content,
                author="seed",
                published_at=now if status == "published" else None,
            )
            db.add(version)
            if status == "published":
                sync_published_copy(row, version)

    await _seed_users(db)
    await db.commit()


async def _seed_users(db: AsyncSession) -> None:
    if settings.initial_admin_username and settings.initial_admin_password:
        exists = await db.scalar(select(User).where(User.username == settings.initial_admin_username))
        if exists is None:
            db.add(
                User(
                    username=settings.initial_admin_username,
                    full_name="Администратор",
                    password_hash=hash_password(settings.initial_admin_password),
                    role="admin",
                )
            )

    if not settings.seed_demo_users:
        return

    team = await db.scalar(select(Team).where(Team.name == "Демо-команда"))
    if team is None:
        team = Team(name="Демо-команда")
        db.add(team)
        await db.flush()

    demo = [
        ("manager1", "Менеджер Один", "manager", team.id),
        ("manager2", "Менеджер Два", "manager", team.id),
        ("manager3", "Менеджер Три", "manager", team.id),
        ("lead1", "Руководитель Демо", "sales_lead", team.id),
        ("trainer1", "Методолог Демо", "training", None),
        ("product1", "Продукт Демо", "product", None),
        ("compliance1", "Комплаенс Демо", "compliance", None),
        ("admin", "Админ Демо", "admin", None),
    ]
    for username, full_name, role, team_id in demo:
        if await db.scalar(select(User).where(User.username == username)) is None:
            db.add(
                User(
                    username=username,
                    full_name=full_name,
                    password_hash=hash_password(settings.demo_users_password),
                    role=role,
                    team_id=team_id,
                )
            )


def load_rubric(rubric_id: str) -> dict:
    rubrics_data = _load("rubric.json")
    for rubric in rubrics_data["rubrics"]:
        if rubric["id"] == rubric_id:
            return rubric
    raise ValueError(f"Rubric not found: {rubric_id}")


def list_rubrics() -> list[dict]:
    return _load("rubric.json")["rubrics"]
