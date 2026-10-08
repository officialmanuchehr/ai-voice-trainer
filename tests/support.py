"""Shared setup for the Phase 2 test modules (not collected by pytest: only
test_*.py is, see pytest.ini).

Configures an offline app — throwaway SQLite, stub providers, demo users —
unless another test module in the same run already imported the app with the
same configuration. Helpers create their own uniquely named products,
scenarios, teams and users, so tests never depend on seed state left by other
tests or on execution order.
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

if "app.main" not in sys.modules:
    os.environ.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{Path(tempfile.mkdtemp()) / 'test.db'}",
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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "demo12345"
SEED_SCENARIO = "scn_merchant_onboarding_medium_01"
CRITERIA = ["contact", "needs", "questions", "listening", "relevance", "value", "objections", "correctness", "no_misselling", "next_step"]
ALL_ROLES_USERS = {
    "manager": "manager1",
    "sales_lead": "lead1",
    "training": "trainer1",
    "product": "product1",
    "compliance": "compliance1",
    "admin": "admin",
}


@pytest.fixture(scope="module")
def server():
    with TestClient(app) as client:  # runs lifespan -> init_db (idempotent)
        yield client


def _live_scenarios() -> set[str]:
    listing = login("trainer1").get("/admin/scenarios").json()
    return {item["id"] for item in listing if item["published_version"]}


@pytest.fixture(scope="module", autouse=True)
def archive_published_scenarios(server):
    """Leaves the shared catalogue as it was: any scenario that became live
    while a module ran is archived when the module finishes, so other test
    modules (which may assert on the exact catalogue) are unaffected by
    execution order."""
    before = _live_scenarios()
    yield
    trainer = login("trainer1")
    for item in trainer.get("/admin/scenarios").json():
        if item["published_version"] and item["id"] not in before:
            trainer.post(f"/admin/scenarios/{item['id']}/versions/{item['published_version']}/status", json={"status": "archived"})


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def login(username: str, password: str = PASSWORD) -> TestClient:
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


def ok(response, status: int = 200):
    assert response.status_code == status, f"{response.status_code}: {response.text}"
    return response.json()


# ------------------------------------------------------------ content setup


def kb_data(product_id: str, **overrides) -> dict:
    data = {
        "id": product_id,
        "name": f"Продукт {product_id}",
        "segment": "тестовый сегмент",
        "approved_facts": [{"id": "fact_1", "type": "condition", "text": "Проверенный тестовый факт."}],
        "approved_arguments": [],
        "objections": [],
        "disclaimers": [],
        "forbidden": [],
        "critical_errors": [],
    }
    data.update(overrides)
    return data


def publish_kb(product_id: str, version: str, data: dict) -> None:
    ok(login("product1").post(f"/admin/kb/{product_id}/versions", json={"version": version, "data": data}))
    ok(login("compliance1").post(f"/admin/kb/{product_id}/versions/{version}/status", json={"status": "approved"}))
    ok(login("product1").post(f"/admin/kb/{product_id}/versions/{version}/status", json={"status": "published"}))


def new_product(prefix: str = "p2", publish: bool = True, **kb_overrides) -> str:
    product_id = uid(prefix)
    if publish:
        publish_kb(product_id, "1.0.0", kb_data(product_id, **kb_overrides))
    else:
        ok(login("product1").post(f"/admin/kb/{product_id}/versions", json={"version": "1.0.0", "data": kb_data(product_id, **kb_overrides)}))
    return product_id


def seed_scenario_data() -> dict:
    return ok(login("admin").get(f"/admin/scenarios/{SEED_SCENARIO}/versions/1"))["data"]


def scenario_data(product_id: str, **overrides) -> dict:
    data = {**seed_scenario_data(), "product_id": product_id, "title": uid("Сценарий")}
    data.update(overrides)
    return data


def create_scenario(data: dict) -> str:
    return ok(login("trainer1").post("/admin/scenarios", json={"data": data}))["id"]


def approve_and_publish_scenario(scenario_id: str, version: int) -> None:
    ok(login("product1").post(f"/admin/scenarios/{scenario_id}/versions/{version}/status", json={"status": "approved"}))
    ok(login("trainer1").post(f"/admin/scenarios/{scenario_id}/versions/{version}/status", json={"status": "published"}))


def published_scenario(product_id: str, **overrides) -> str:
    scenario_id = create_scenario(scenario_data(product_id, **overrides))
    approve_and_publish_scenario(scenario_id, 1)
    return scenario_id


def new_team_with_users(roles: dict[str, str]) -> dict[str, str]:
    """Creates a team plus one user per key (role as value); returns key -> username."""
    admin = login("admin")
    team = ok(admin.post("/admin/teams", json={"name": uid("Команда")}))
    usernames = {}
    for key, role in roles.items():
        username = uid(key)
        ok(admin.post("/admin/users", json={"username": username, "full_name": username, "role": role, "password": PASSWORD, "team_id": team["id"]}))
        usernames[key] = username
    return usernames


# ------------------------------------------------------- provider capture


class Capture:
    """Replaces the stub providers' methods for one test and records what the
    application hands them (system prompts, KB snapshots, rubrics)."""

    def __init__(self, monkeypatch, breakdown=None, claims=(), critical_errors=()):
        self.prompts: list[str] = []
        self.claim_kbs: list[dict] = []
        self.score_rubrics: list[dict] = []
        breakdown = breakdown or [{"criterion_id": c, "score": 50, "max": 100} for c in CRITERIA]

        async def respond(system_prompt, messages):
            self.prompts.append(system_prompt)
            return "Слушаю."

        async def verify_claims(transcript, kb):
            self.claim_kbs.append(kb)
            return [dict(c) for c in claims]

        async def score(transcript, rubric, claim_checks):
            self.score_rubrics.append(rubric)
            return {
                "breakdown": [dict(b) for b in breakdown],
                "critical_errors": [dict(e) for e in critical_errors],
                "feedback": {"summary": "s", "strengths": [], "growth_areas": [], "better_examples": [], "next_skill": None},
            }

        monkeypatch.setattr(main.dialog_provider, "respond", respond)
        monkeypatch.setattr(main.scoring_provider, "verify_claims", verify_claims)
        monkeypatch.setattr(main.scoring_provider, "score", score)


def start_session(client: TestClient, scenario_id: str) -> dict:
    return ok(client.post("/sessions", json={"scenario_id": scenario_id}))


def say(client: TestClient, session_id: str, text: str = "Добрый день! Расскажите о вашем бизнесе?") -> dict:
    return ok(client.post(f"/sessions/{session_id}/turns", json={"text": text}))


def finish_and_score(client: TestClient, session_id: str) -> dict:
    ok(client.post(f"/sessions/{session_id}/finish"))
    assert ok(client.post(f"/sessions/{session_id}/score-run"))["status"] == "finished"
    return ok(client.get(f"/sessions/{session_id}/score"))
