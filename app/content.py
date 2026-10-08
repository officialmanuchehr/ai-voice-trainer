"""Versioned content (scenarios, knowledge base): lookups, validation and the
draft -> approved -> published -> archived lifecycle (PRD §12–13)."""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeBase, Scenario, ScenarioVersion, User
from app.models import Session as SessionModel
from app.security import (
    KB_APPROVE_ROLES,
    KB_EDIT_ROLES,
    KB_PUBLISH_ROLES,
    SCENARIO_APPROVE_ROLES,
    SCENARIO_EDIT_ROLES,
    SCENARIO_PUBLISH_ROLES,
)
from app.seed_loader import list_rubrics

DIFFICULTIES = ("easy", "medium", "hard")

# Training topics a scenario can be tagged with (catalogue filter, admin).
# A fixed list rather than free text so every page groups by the same ids.
TOPICS = {
    "conversation_structure": "Структура разговора",
    "needs_discovery": "Выявление потребностей",
    "objections": "Работа с возражениями",
    "competitor_switch": "Переход из другого банка",
    "pressure_honesty": "Давление клиента и честные условия",
    "difficult_client": "Сложный клиент",
    "next_step": "Договорённость о следующем шаге",
}


def topic_list(ids: list[str] | None) -> list[dict]:
    return [{"id": t, "name": TOPICS[t]} for t in ids or [] if t in TOPICS]

_TRANSITIONS = {
    "draft": {"approved", "archived"},
    "approved": {"published", "draft", "archived"},
    "published": {"archived"},
    "archived": set(),
}


@dataclass(frozen=True)
class TransitionDecision:
    allowed: bool
    status_code: int | None = None
    detail: str | None = None


def _roles_for(version: ScenarioVersion | KnowledgeBase) -> tuple[set, set, set]:
    if isinstance(version, ScenarioVersion):
        return SCENARIO_EDIT_ROLES, SCENARIO_APPROVE_ROLES, SCENARIO_PUBLISH_ROLES
    if isinstance(version, KnowledgeBase):
        return KB_EDIT_ROLES, KB_APPROVE_ROLES, KB_PUBLISH_ROLES
    raise TypeError(f"no approval policy for {type(version).__name__}")


def can_transition(user: User, version: ScenarioVersion | KnowledgeBase, target: str) -> TransitionDecision:
    """The single approval policy point for scenario and KB lifecycle changes.

    Today it encodes only the lifecycle graph and the role sets from
    app/security.py. `version.author` and `version.approved_by` are available
    here deliberately: rules that depend on who wrote or approved a version
    (e.g. "the approver must not be the author") belong in this function once
    the bank confirms them (decisions B-1/B-2) — not in the
    endpoints."""
    edit_roles, approve_roles, publish_roles = _roles_for(version)
    current = version.status
    if target not in _TRANSITIONS.get(current, set()):
        return TransitionDecision(False, 400, f"переход {current} → {target} недопустим")
    allowed = {
        "approved": approve_roles,
        "draft": edit_roles | approve_roles,
        "published": publish_roles,
        "archived": publish_roles,
    }[target]
    if user.role not in allowed:
        return TransitionDecision(False, 403, f"роль не может переводить в статус {target}")
    return TransitionDecision(True)


def require_transition(user: User, version: ScenarioVersion | KnowledgeBase, target: str) -> None:
    decision = can_transition(user, version, target)
    if not decision.allowed:
        raise HTTPException(status_code=decision.status_code, detail=decision.detail)


# KB sections whose entries may carry `needs_review: true` (developer
# placeholders the product team has not confirmed yet).
_REVIEWABLE_KB_SECTIONS = ("approved_facts", "approved_arguments", "objections", "disclaimers")


def kb_review_blockers(data: dict) -> list[dict]:
    """Content that is not yet bank-confirmed: every entry flagged
    `needs_review`, plus a top-level `draft_note`. A KB version with any of
    these must not become approved or published product truth."""
    blockers = []
    if data.get("draft_note"):
        blockers.append({"section": "draft_note"})
    for section in _REVIEWABLE_KB_SECTIONS:
        for entry in data.get(section) or []:
            if isinstance(entry, dict) and entry.get("needs_review"):
                blockers.append({"section": section, "id": entry.get("id")})
    return blockers


def kb_review_message(prefix: str, blockers: list[dict]) -> str:
    items = [b.get("id") or b["section"] for b in blockers]
    return f"{prefix}: не проверено {len(blockers)} — {', '.join(items)}. Снимите needs_review и draft_note после проверки продуктовой командой."


async def published_kb(db: AsyncSession, product_id: str) -> KnowledgeBase | None:
    return await db.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.product_id == product_id, KnowledgeBase.status == "published")
        .order_by(KnowledgeBase.id.desc())
    )


async def session_content(db: AsyncSession, session: SessionModel) -> tuple[dict, KnowledgeBase]:
    """The scenario version and KB snapshot a session is bound to — never the
    current ones, so an edit after the session started can't change it."""
    version = await db.scalar(
        select(ScenarioVersion).where(
            ScenarioVersion.scenario_id == session.scenario_id,
            ScenarioVersion.version == (session.scenario_version or 1),
        )
    )
    if version is not None:
        data = version.data
    else:
        scenario = await db.get(Scenario, session.scenario_id)
        data = {
            "product_id": scenario.product_id,
            "title": scenario.title or scenario.id,
            "difficulty": scenario.difficulty,
            "goal": scenario.goal,
            "rubric_id": scenario.rubric_id,
            "client_profile": scenario.client_profile,
            "config": {},
        }
    kb = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.product_id == data["product_id"],
            KnowledgeBase.version == session.kb_version,
        )
    )
    if kb is None:
        raise HTTPException(status_code=500, detail="knowledge base snapshot missing for session.kb_version")
    return data, kb


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def _str_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _bad(f"{field}: ожидается список строк")
    return [v.strip() for v in value if v.strip()]


def validate_scenario_content(content: dict, product_ids: set[str]) -> dict:
    if not isinstance(content, dict):
        raise _bad("сценарий должен быть объектом")
    for field in ("product_id", "title", "difficulty", "goal", "rubric_id"):
        if not isinstance(content.get(field), str) or not content[field].strip():
            raise _bad(f"поле {field} обязательно")
    if content["product_id"] not in product_ids:
        raise _bad(f"неизвестный продукт: {content['product_id']}")
    if content["difficulty"] not in DIFFICULTIES:
        raise _bad(f"сложность должна быть одной из {', '.join(DIFFICULTIES)}")
    rubric = next((r for r in list_rubrics() if r["id"] == content["rubric_id"]), None)
    if rubric is None:
        raise _bad(f"неизвестная рубрика: {content['rubric_id']}")

    profile = content.get("client_profile")
    if not isinstance(profile, dict) or not profile:
        raise _bad("client_profile должен быть непустым объектом")
    variants = profile.get("variants", {})
    if not isinstance(variants, dict) or not all(isinstance(v, list) and v for v in variants.values()):
        raise _bad("client_profile.variants: ожидается {поле: [варианты]}")

    topics = content.get("topics") or []
    if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
        raise _bad("topics: ожидается список тем")
    unknown = [t for t in topics if t not in TOPICS]
    if unknown:
        raise _bad(f"неизвестная тема: {', '.join(unknown)}")

    config = content.get("config") or {}
    if not isinstance(config, dict):
        raise _bad("config должен быть объектом")
    criteria_ids = {c["id"] for c in rubric["criteria"]}
    weights = config.get("criteria_weights") or {}
    if not isinstance(weights, dict):
        raise _bad("criteria_weights должен быть объектом")
    clean_weights = {}
    for criterion_id, weight in weights.items():
        if criterion_id not in criteria_ids:
            raise _bad(f"неизвестный критерий: {criterion_id}")
        if not isinstance(weight, int) or weight < 0 or weight > 100:
            raise _bad(f"вес {criterion_id} должен быть целым числом 0–100")
        clean_weights[criterion_id] = weight
    effective = {c["id"]: clean_weights.get(c["id"], c["weight"]) for c in rubric["criteria"]}
    if sum(effective.values()) <= 0:
        raise _bad("хотя бы один критерий должен иметь вес больше 0")

    return {
        "product_id": content["product_id"],
        "title": content["title"].strip(),
        "difficulty": content["difficulty"],
        "goal": content["goal"].strip(),
        "rubric_id": content["rubric_id"],
        "client_profile": profile,
        "topics": list(dict.fromkeys(topics)),
        "config": {
            "learning_goal": str(config.get("learning_goal") or "").strip(),
            "criteria_weights": clean_weights,
            "good_examples": _str_list(config.get("good_examples"), "good_examples"),
            "feedback_hints": _str_list(config.get("feedback_hints"), "feedback_hints"),
        },
    }


def validate_kb_content(data: dict, product_id: str) -> dict:
    if not isinstance(data, dict):
        raise _bad("база знаний должна быть объектом")
    if data.get("id") != product_id:
        raise _bad(f"поле id должно совпадать с продуктом ({product_id})")
    for field in ("name", "segment"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise _bad(f"поле {field} обязательно")

    def entries(field: str, required: tuple[str, ...]) -> list:
        value = data.get(field, [])
        if not isinstance(value, list):
            raise _bad(f"{field}: ожидается список")
        ids = set()
        for item in value:
            if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip() for k in required):
                raise _bad(f"{field}: у каждой записи должны быть поля {', '.join(required)}")
            if item["id"] in ids:
                raise _bad(f"{field}: повторяющийся id {item['id']}")
            ids.add(item["id"])
        return value

    if not entries("approved_facts", ("id", "text")):
        raise _bad("нужен хотя бы один утверждённый факт (approved_facts)")
    entries("approved_arguments", ("id", "text"))
    entries("objections", ("id", "trigger", "approved_response"))
    entries("disclaimers", ("id", "text"))
    _str_list(data.get("forbidden"), "forbidden")
    _str_list(data.get("critical_errors"), "critical_errors")
    return data
