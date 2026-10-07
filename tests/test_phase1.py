"""Phase 1: A0-1 unreviewed-KB guard, A0-5 explained
score cap, A1-0 approval policy hook (no behaviour change).

Same setup as test_access.py — in-process app, throwaway SQLite, stub
providers, demo users:

    pytest tests/test_phase1.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

_DB_FILE = Path(tempfile.mkdtemp()) / "test.db"
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{_DB_FILE}",
        "STT_PROVIDER": "stub",
        "DIALOG_PROVIDER": "stub",
        "SCORING_PROVIDER": "stub",
        "TTS_PROVIDER": "stub",
        "AUTO_INIT_DB": "true",
        "SEED_DEMO_USERS": "true",
        "DEMO_USERS_PASSWORD": "demo12345",
        "SECRET_KEY": "test-secret",
        "INITIAL_ADMIN_USERNAME": "",
        "INITIAL_ADMIN_PASSWORD": "",
        "BASIC_AUTH_USERNAME": "",
        "BASIC_AUTH_PASSWORD": "",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.content import can_transition, kb_review_blockers  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import KnowledgeBase, ScenarioVersion, User  # noqa: E402
from app.scoring_math import cap_reason, compute_total, finalize  # noqa: E402
from app.security import (  # noqa: E402
    KB_APPROVE_ROLES,
    KB_EDIT_ROLES,
    KB_PUBLISH_ROLES,
    ROLES,
    SCENARIO_APPROVE_ROLES,
    SCENARIO_EDIT_ROLES,
    SCENARIO_PUBLISH_ROLES,
)

PASSWORD = "demo12345"
SCENARIO = "scn_merchant_onboarding_medium_01"
STATUSES = ("draft", "approved", "published", "archived")


@pytest.fixture(scope="module")
def server():
    with TestClient(app) as client:
        yield client


def login(username: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


def run(coro):
    return asyncio.run(coro)


async def _set_kb(product_id: str, version: str, **fields):
    async with SessionLocal() as db:
        kb = await db.scalar(
            select(KnowledgeBase).where(KnowledgeBase.product_id == product_id, KnowledgeBase.version == version)
        )
        for key, value in fields.items():
            setattr(kb, key, value)
        await db.commit()


def kb_status(client, product_id, version):
    return client.get(f"/admin/kb/{product_id}/versions/{version}").json()["status"]


def set_kb_status(client, product_id, version, status):
    return client.post(f"/admin/kb/{product_id}/versions/{version}/status", json={"status": status})


def new_product(product_id: str, **extra) -> None:
    data = {
        "id": product_id,
        "name": f"Тестовый продукт {product_id}",
        "segment": "тест",
        "approved_facts": [{"id": "fact_test", "text": "Тестовый факт."}],
        **extra,
    }
    response = login("product1").post(f"/admin/kb/{product_id}/versions", json={"version": "1.0.0", "data": data})
    assert response.status_code == 200, response.text


# ===================================================== A1-0 approval policy


def _legacy_check_transition(current, target, role, edit_roles, approve_roles, publish_roles):
    """Frozen copy of app.content.check_transition before Phase 1 — the oracle
    the new policy must match exactly."""
    transitions = {
        "draft": {"approved", "archived"},
        "approved": {"published", "draft", "archived"},
        "published": {"archived"},
        "archived": set(),
    }
    if target not in transitions.get(current, set()):
        raise HTTPException(status_code=400, detail=f"переход {current} → {target} недопустим")
    allowed = {
        "approved": approve_roles,
        "draft": edit_roles | approve_roles,
        "published": publish_roles,
        "archived": publish_roles,
    }[target]
    if role not in allowed:
        raise HTTPException(status_code=403, detail=f"роль не может переводить в статус {target}")


def _legacy_outcome(*args):
    try:
        _legacy_check_transition(*args)
    except HTTPException as exc:
        return (False, exc.status_code, exc.detail)
    return (True, None, None)


KINDS = [
    (ScenarioVersion, (SCENARIO_EDIT_ROLES, SCENARIO_APPROVE_ROLES, SCENARIO_PUBLISH_ROLES)),
    (KnowledgeBase, (KB_EDIT_ROLES, KB_APPROVE_ROLES, KB_PUBLISH_ROLES)),
]


@pytest.mark.parametrize("model,role_sets", KINDS, ids=["scenario", "kb"])
def test_policy_matches_previous_rules_exhaustively(model, role_sets):
    checked = 0
    for role in [*ROLES, "unknown_role"]:
        for current in STATUSES:
            for target in [*STATUSES, "bogus"]:
                version = model(status=current, author="someone")
                decision = can_transition(User(role=role, username="u"), version, target)
                got = (decision.allowed, decision.status_code, decision.detail)
                assert got == _legacy_outcome(current, target, role, *role_sets), (role, current, target)
                checked += 1
    assert checked == 7 * 4 * 5


def test_policy_has_no_four_eyes_rule_yet():
    """Bank decision B-1 is pending: an author may still approve their own
    version when their role allows it, exactly as before."""
    kb = KnowledgeBase(status="draft", author="compliance1")
    assert can_transition(User(role="compliance", username="compliance1"), kb, "approved").allowed
    scenario = ScenarioVersion(status="draft", author="admin")
    assert can_transition(User(role="admin", username="admin"), scenario, "approved").allowed
    approved = ScenarioVersion(status="approved", author="admin", approved_by="admin")
    assert can_transition(User(role="admin", username="admin"), approved, "published").allowed


def test_policy_rejects_unknown_content_type():
    with pytest.raises(TypeError):
        can_transition(User(role="admin", username="admin"), object(), "approved")


# ===================================================== A0-1 KB review guard


def test_review_blockers_unit():
    assert kb_review_blockers({"approved_facts": [{"id": "f1", "text": "x"}]}) == []
    blockers = kb_review_blockers(
        {
            "draft_note": "ЧЕРНОВИК",
            "approved_facts": [{"id": "f1", "needs_review": True}, {"id": "f2", "needs_review": False}],
            "approved_arguments": [{"id": "a1", "needs_review": True}],
            "objections": [{"id": "o1", "needs_review": True}],
            "disclaimers": [{"id": "d1", "needs_review": True}],
        }
    )
    assert blockers == [
        {"section": "draft_note"},
        {"section": "approved_facts", "id": "f1"},
        {"section": "approved_arguments", "id": "a1"},
        {"section": "objections", "id": "o1"},
        {"section": "disclaimers", "id": "d1"},
    ]


def _placeholder_kb_version(client, product_id="rko"):
    item = next(p for p in client.get("/admin/kb").json() if p["product_id"] == product_id)
    return item["versions"][-1]["version"]


def test_unreviewed_kb_cannot_be_approved(server):
    compliance = login("compliance1")
    version = _placeholder_kb_version(compliance)
    assert kb_status(compliance, "rko", version) == "draft"

    response = set_kb_status(compliance, "rko", version, "approved")
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "kb_unreviewed"
    ids = {b.get("id") for b in body["unreviewed"]}
    assert {"section": "draft_note"} in body["unreviewed"]
    assert "fact_rko_account" in ids
    assert len([b for b in body["unreviewed"] if b["section"] == "approved_facts"]) == 5
    assert "fact_rko_account" in body["detail"]  # readable message for the existing admin UI

    assert kb_status(compliance, "rko", version) == "draft"  # no partial transition


def test_unreviewed_kb_cannot_be_published(server):
    """A placeholder KB that reached `approved` some other way (e.g. before
    this guard existed) still can't be published."""
    product = login("product1")
    version = _placeholder_kb_version(product, "payroll_project")
    run(_set_kb("payroll_project", version, status="approved"))
    try:
        response = set_kb_status(product, "payroll_project", version, "published")
        assert response.status_code == 409
        assert response.json()["code"] == "kb_unreviewed"
        assert kb_status(product, "payroll_project", version) == "approved"
        assert login("manager1").get("/scenarios").json()[0]["product_id"] == "merchant_onboarding"
    finally:
        run(_set_kb("payroll_project", version, status="draft"))


def test_draft_note_alone_blocks_approval(server):
    new_product("p1_note", draft_note="Заготовка разработчика")
    response = set_kb_status(login("compliance1"), "p1_note", "1.0.0", "approved")
    assert response.status_code == 409
    assert response.json()["unreviewed"] == [{"section": "draft_note"}]


def test_blocked_transition_writes_no_audit(server):
    admin = login("admin")
    before = [r for r in admin.get("/admin/audit?entity_type=knowledge_base").json() if r["action"] == "kb.status"]
    set_kb_status(login("compliance1"), "rko", _placeholder_kb_version(admin), "approved")
    after = [r for r in admin.get("/admin/audit?entity_type=knowledge_base").json() if r["action"] == "kb.status"]
    assert len(after) == len(before)


def test_clean_kb_follows_existing_lifecycle(server):
    new_product("p1_clean")
    assert set_kb_status(login("compliance1"), "p1_clean", "1.0.0", "approved").status_code == 200
    assert set_kb_status(login("product1"), "p1_clean", "1.0.0", "published").status_code == 200
    product = login("product1")
    assert kb_status(product, "p1_clean", "1.0.0") == "published"
    # Published versions stay immutable (unchanged behaviour).
    edit = product.put("/admin/kb/p1_clean/versions/1.0.0", json={"data": {"id": "p1_clean"}})
    assert edit.status_code == 409


def test_role_and_graph_checks_still_come_first(server):
    """An unauthorised role gets 403 and an invalid transition 400 — the
    review guard doesn't leak content details ahead of authorisation."""
    version = _placeholder_kb_version(login("admin"))
    assert set_kb_status(login("trainer1"), "rko", version, "approved").status_code == 403
    assert set_kb_status(login("product1"), "rko", version, "published").status_code == 400


def _scenario_data(product_id: str, title: str) -> dict:
    admin = login("admin")
    data = admin.get(f"/admin/scenarios/{SCENARIO}/versions/1").json()["data"]
    return {**data, "product_id": product_id, "title": title}


def _create_and_approve_scenario(product_id: str, title: str) -> str:
    created = login("trainer1").post("/admin/scenarios", json={"data": _scenario_data(product_id, title)})
    assert created.status_code == 200, created.text
    scenario_id = created.json()["id"]
    approved = login("product1").post(f"/admin/scenarios/{scenario_id}/versions/1/status", json={"status": "approved"})
    assert approved.status_code == 200, approved.text
    return scenario_id


def test_scenario_publish_requires_published_kb(server):
    new_product("p1_unpublished")
    scenario_id = _create_and_approve_scenario("p1_unpublished", "Сценарий без БЗ")
    response = login("trainer1").post(f"/admin/scenarios/{scenario_id}/versions/1/status", json={"status": "published"})
    assert response.status_code == 409
    assert "опубликуйте базу знаний" in response.json()["detail"]


def test_scenario_cannot_publish_against_unreviewed_published_kb(server):
    new_product("p1_legacy")
    set_kb_status(login("compliance1"), "p1_legacy", "1.0.0", "approved")
    set_kb_status(login("product1"), "p1_legacy", "1.0.0", "published")
    # Simulate a KB published before the guard existed, still carrying a placeholder.
    run(
        _set_kb(
            "p1_legacy",
            "1.0.0",
            data={
                "id": "p1_legacy",
                "name": "Legacy",
                "segment": "тест",
                "approved_facts": [{"id": "fact_old", "text": "?", "needs_review": True}],
            },
        )
    )
    scenario_id = _create_and_approve_scenario("p1_legacy", "Сценарий на старой БЗ")
    trainer = login("trainer1")
    response = trainer.post(f"/admin/scenarios/{scenario_id}/versions/1/status", json={"status": "published"})
    assert response.status_code == 409
    assert response.json()["code"] == "kb_not_clean"
    assert response.json()["unreviewed"] == [{"section": "approved_facts", "id": "fact_old"}]
    versions = next(s for s in trainer.get("/admin/scenarios").json() if s["id"] == scenario_id)
    assert versions["versions"][0]["status"] == "approved"
    assert versions["published_version"] is None


def test_scenario_publishes_against_clean_kb_and_binds_versions(server):
    scenario_id = _create_and_approve_scenario("p1_clean", "Сценарий на чистой БЗ")
    trainer = login("trainer1")
    published = trainer.post(f"/admin/scenarios/{scenario_id}/versions/1/status", json={"status": "published"})
    assert published.status_code == 200
    try:
        session = login("manager3").post("/sessions", json={"scenario_id": scenario_id}).json()
        assert (session["scenario_version"], session["kb_version"]) == (1, "1.0.0")
    finally:
        # Keep the manager catalogue as other test modules expect it.
        trainer.post(f"/admin/scenarios/{scenario_id}/versions/1/status", json={"status": "archived"})


# ===================================================== A0-5 score cap


def test_cap_never_raises_a_score():
    weights = {"a": 100}

    def total(score, critical):
        return compute_total([{"criterion_id": "a", "score": score, "max": 100}], weights, critical)

    assert total(100, True) == 60
    assert total(74, True) == 60
    assert total(42, True) == 42
    assert total(74, False) == 74
    assert total(100, False) == 100


def _full_marks(rubric_criteria):
    return [{"criterion_id": c["id"], "score": c["weight"], "max": c["weight"]} for c in rubric_criteria]


def test_cap_reason_unit():
    weights = {"a": 100}
    breakdown = [{"criterion_id": "a", "score": 74, "max": 100}]
    error = {"type": "Гарантия, которой нет в утверждённых материалах.", "quote": "гарантирую", "explanation": "x"}
    claim = {"verdict": "unapproved", "claim_text": "лимит 500 000", "turn_index": 3, "reason": "нет в БЗ"}

    assert cap_reason({"breakdown": breakdown, "critical_errors": []}, [], weights) is None
    assert cap_reason({"breakdown": [{"criterion_id": "a", "score": 42, "max": 100}], "critical_errors": [error]}, [], weights) is None

    by_error = cap_reason({"breakdown": breakdown, "critical_errors": [error]}, [], weights)
    assert by_error == {
        "limit": 60,
        "calculated_total": 74,
        "triggers": [{"kind": "critical_error", "type": error["type"], "quote": "гарантирую", "explanation": "x"}],
    }

    by_claim = cap_reason({"breakdown": breakdown, "critical_errors": []}, [claim], weights)
    assert by_claim["triggers"] == [
        {"kind": "claim", "verdict": "unapproved", "claim_text": "лимит 500 000", "turn_index": 3, "reason": "нет в БЗ"}
    ]
    forbidden = {**claim, "verdict": "forbidden"}
    assert cap_reason({"breakdown": breakdown, "critical_errors": []}, [forbidden], weights)["triggers"][0]["verdict"] == "forbidden"

    approved = {**claim, "verdict": "approved"}
    assert cap_reason({"breakdown": breakdown, "critical_errors": []}, [approved], weights) is None


def test_cap_reason_agrees_with_finalize():
    """For every trigger combination, cap_reason is present exactly when
    finalize() lowered the total, and its calculated_total is the uncapped
    value finalize() would have produced."""
    rubric = {"criteria": [{"id": "a", "weight": 60}, {"id": "b", "weight": 40}]}
    claim = {"verdict": "unapproved", "claim_text": "x", "turn_index": 1}
    for a, b in [(60, 40), (50, 30), (20, 20), (0, 0)]:
        for errors, claims in [([], []), ([{"type": "t"}], []), ([], [claim]), ([{"type": "t"}], [claim])]:
            breakdown = [{"criterion_id": "a", "score": a, "max": 60}, {"criterion_id": "b", "score": b, "max": 40}]
            result = finalize({"breakdown": [dict(i) for i in breakdown], "critical_errors": errors}, rubric, claims, None)
            uncapped = a + b
            cap = cap_reason(result, claims, {"a": 60, "b": 40})
            assert (cap is not None) == (result["total"] < uncapped)
            if cap:
                assert cap["calculated_total"] == uncapped and result["total"] == 60


def _score_with(server, monkeypatch, *, breakdown, critical_errors=(), claims=()):
    import app.main as main

    async def verify_claims(transcript, kb):
        return [dict(c) for c in claims]

    async def score(transcript, rubric, claim_checks):
        return {
            "breakdown": [dict(i) for i in breakdown],
            "critical_errors": [dict(e) for e in critical_errors],
            "feedback": {"summary": "s", "strengths": [], "growth_areas": [], "better_examples": [], "next_skill": None},
        }

    monkeypatch.setattr(main.scoring_provider, "verify_claims", verify_claims)
    monkeypatch.setattr(main.scoring_provider, "score", score)
    manager = login("manager3")
    session_id = manager.post("/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    manager.post(f"/sessions/{session_id}/turns", json={"text": "Добрый день!"})
    manager.post(f"/sessions/{session_id}/finish")
    assert manager.post(f"/sessions/{session_id}/score-run").json()["status"] == "finished"
    result = manager.get(f"/sessions/{session_id}/score").json()
    # Version linkage unchanged.
    assert (result["scenario_version"], result["kb_version"]) == (1, "1.0.0")
    return result


def _uniform(percent):
    """Every criterion at the same share — the total is `percent` whatever the weights."""
    criteria = ["contact", "needs", "questions", "listening", "relevance", "value", "objections", "correctness", "no_misselling", "next_step"]
    return [{"criterion_id": c, "score": percent, "max": 100} for c in criteria]


CRITICAL = {"type": "Обещание ставки/комиссии/срока/тарифа, которого нет в БЗ.", "quote": "ставка 5%", "explanation": "нет в БЗ"}
UNAPPROVED = {"claim_text": "лимит 500 000", "turn_index": 1, "verdict": "unapproved", "matched_entry_id": None, "reason": "нет в БЗ"}


def test_api_100_with_critical_error_is_capped_and_explained(server, monkeypatch):
    result = _score_with(server, monkeypatch, breakdown=_uniform(100), critical_errors=[CRITICAL])
    assert result["total"] == 60
    assert result["cap_reason"]["calculated_total"] == 100
    assert result["cap_reason"]["triggers"] == [{"kind": "critical_error", "type": CRITICAL["type"], "quote": "ставка 5%", "explanation": "нет в БЗ"}]


def test_api_74_with_unsupported_claim_only_is_capped_and_explained(server, monkeypatch):
    """The case the audit flagged: the cap fires from a claim verdict while the
    scorer returned no critical_errors entry — now the reason is explicit."""
    result = _score_with(server, monkeypatch, breakdown=_uniform(74), claims=[UNAPPROVED])
    assert result["critical_errors"] == []
    assert result["total"] == 60
    assert result["cap_reason"]["calculated_total"] == 74
    assert result["cap_reason"]["triggers"][0]["kind"] == "claim"
    assert result["cap_reason"]["triggers"][0]["claim_text"] == "лимит 500 000"


def test_api_forbidden_claim_caps(server, monkeypatch):
    forbidden = {**UNAPPROVED, "verdict": "forbidden"}
    result = _score_with(server, monkeypatch, breakdown=_uniform(90), claims=[forbidden])
    assert result["total"] == 60
    assert result["cap_reason"]["triggers"][0]["verdict"] == "forbidden"


def test_api_42_with_critical_error_is_not_capped(server, monkeypatch):
    result = _score_with(server, monkeypatch, breakdown=_uniform(42), critical_errors=[CRITICAL])
    assert result["total"] == 42
    assert result["cap_reason"] is None
    assert result["critical_errors"]  # still reported, just not a cap


def test_api_no_trigger_leaves_score_unchanged(server, monkeypatch):
    approved = {**UNAPPROVED, "verdict": "approved"}
    result = _score_with(server, monkeypatch, breakdown=_uniform(87), claims=[approved])
    assert result["total"] == 87
    assert result["cap_reason"] is None
