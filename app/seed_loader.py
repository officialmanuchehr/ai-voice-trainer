import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeBase, Product, Scenario

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


def _load(name: str) -> dict:
    with open(SEED_DIR / name, encoding="utf-8") as f:
        return json.load(f)


async def load_seed(db: AsyncSession) -> None:
    kb_data = _load("knowledge_base.json")
    scenarios_data = _load("scenarios.json")

    kb_version = kb_data["kb_version"]

    for product in kb_data["products"]:
        product_id = product["id"]

        existing_product = await db.get(Product, product_id)
        if existing_product is None:
            db.add(Product(id=product_id, name=product["name"], segment=product["segment"]))
        else:
            existing_product.name = product["name"]
            existing_product.segment = product["segment"]

        existing_kb = await db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.product_id == product_id,
                KnowledgeBase.version == kb_version,
            )
        )
        if existing_kb is None:
            db.add(KnowledgeBase(product_id=product_id, version=kb_version, data=product))
        else:
            existing_kb.data = product

    await db.flush()

    for scenario in scenarios_data["scenarios"]:
        existing_scenario = await db.get(Scenario, scenario["id"])
        if existing_scenario is None:
            db.add(
                Scenario(
                    id=scenario["id"],
                    product_id=scenario["product_id"],
                    client_profile=scenario["client_profile"],
                    difficulty=scenario["difficulty"],
                    goal=scenario["goal"],
                    rubric_id=scenario["rubric_id"],
                )
            )
        else:
            existing_scenario.product_id = scenario["product_id"]
            existing_scenario.client_profile = scenario["client_profile"]
            existing_scenario.difficulty = scenario["difficulty"]
            existing_scenario.goal = scenario["goal"]
            existing_scenario.rubric_id = scenario["rubric_id"]

    await db.commit()


def load_rubric(rubric_id: str) -> dict:
    rubrics_data = _load("rubric.json")
    for rubric in rubrics_data["rubrics"]:
        if rubric["id"] == rubric_id:
            return rubric
    raise ValueError(f"Rubric not found: {rubric_id}")
