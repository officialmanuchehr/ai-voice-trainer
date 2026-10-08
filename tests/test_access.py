"""Access-control and Block 4 regression tests.

Runs the whole app in-process against a throwaway SQLite file, with every
provider on "stub" and the demo users seeded — no network, no API keys:

    pip install -r requirements-dev.txt
    pytest tests/test_access.py
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Settings are read at import time, so the environment must be in place before
# anything from app/ is imported. Real env vars win over .env in pydantic-settings.
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

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASSWORD = "demo12345"
SCENARIO = "scn_merchant_onboarding_medium_01"


@pytest.fixture(scope="module")
def server():
    with TestClient(app) as client:  # context manager runs lifespan -> init_db
        yield client


def login(server, username: str, password: str = PASSWORD) -> TestClient:
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture(scope="module")
def scored_session(server):
    """A finished, scored session owned by manager1."""
    manager = login(server, "manager1")
    session_id = manager.post("/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    assert manager.post(f"/sessions/{session_id}/turns", json={"text": "Добрый день!"}).status_code == 200
    assert manager.post(f"/sessions/{session_id}/finish").json()["status"] == "scoring"
    assert manager.post(f"/sessions/{session_id}/score-run").json()["status"] == "finished"
    return session_id


# ------------------------------------------------------------------ login


def test_health_is_public(server):
    assert server.get("/health").json() == {"status": "ok"}


def test_api_requires_login(server):
    assert TestClient(app).get("/scenarios").status_code == 401


def test_wrong_password_rejected(server):
    response = TestClient(app).post("/auth/login", json={"username": "manager1", "password": "wrong-pass"})
    assert response.status_code == 401


def test_tampered_cookie_rejected(server):
    client = login(server, "manager1")
    token = client.cookies.get("avt_session")
    forged = TestClient(app, cookies={"avt_session": token[:-1] + ("0" if token[-1] != "0" else "1")})
    assert forged.get("/auth/me").status_code == 401


def test_logout(server):
    client = login(server, "manager1")
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401


# ------------------------------------------------------- training session


def test_manager_sees_only_published_scenarios(server):
    scenarios = login(server, "manager1").get("/scenarios").json()
    assert [s["id"] for s in scenarios] == [SCENARIO]


def test_draft_scenario_cannot_be_started(server):
    admin = login(server, "admin")
    drafts = [s for s in admin.get("/admin/scenarios").json() if s["id"] != SCENARIO]
    assert drafts, "seed should contain draft scenarios"
    response = login(server, "manager1").post("/sessions", json={"scenario_id": drafts[0]["id"]})
    assert response.status_code >= 400


def test_full_session_flow(server, scored_session):
    manager = login(server, "manager1")
    score = manager.get(f"/sessions/{scored_session}/score").json()
    assert score["status"] == "finished"
    assert 0 <= score["total"] <= 100
    assert score["own"] is True
    assert any(row["id"] == scored_session for row in manager.get("/me/sessions").json())


def test_dispute(server, scored_session):
    manager = login(server, "manager1")
    assert manager.post(f"/sessions/{scored_session}/dispute", json={"comment": "  "}).status_code == 400
    assert manager.post(f"/sessions/{scored_session}/dispute", json={"comment": "не согласен"}).status_code == 200
    assert manager.get(f"/sessions/{scored_session}/score").json()["dispute"]["comment"] == "не согласен"


def test_aggregate_role_cannot_start_session(server):
    assert login(server, "product1").post("/sessions", json={"scenario_id": SCENARIO}).status_code == 403


# --------------------------------------------------- who sees which session


@pytest.mark.parametrize(
    "username,status",
    [
        ("manager2", 403),  # another manager, same team
        ("trainer1", 403),  # aggregate-only role never sees transcripts
        ("compliance1", 403),
        ("lead1", 200),  # lead of the owner's team
        ("admin", 200),
    ],
)
def test_session_visibility(server, scored_session, username, status):
    client = login(server, username)
    assert client.get(f"/sessions/{scored_session}/score").status_code == status
    assert client.get(f"/sessions/{scored_session}/transcript").status_code == status


@pytest.mark.parametrize("username", ["lead1", "admin"])
def test_only_owner_can_write(server, scored_session, username):
    response = login(server, username).post(f"/sessions/{scored_session}/dispute", json={"comment": "x"})
    assert response.status_code == 403


# ---------------------------------------------------------------- dashboard


@pytest.mark.parametrize(
    "username,status",
    [("manager1", 403), ("lead1", 200), ("trainer1", 200), ("product1", 200), ("compliance1", 200), ("admin", 200)],
)
def test_dashboard_roles(server, scored_session, username, status):
    assert login(server, username).get("/dashboard/data").status_code == status


def test_dashboard_names_only_for_lead_and_admin(server, scored_session):
    assert "Менеджер Один" in login(server, "lead1").get("/dashboard/data").text
    assert "Менеджер Один" in login(server, "admin").get("/dashboard/data").text
    for username in ("trainer1", "product1", "compliance1"):
        assert "Менеджер Один" not in login(server, username).get("/dashboard/data").text


def test_lead_cannot_open_other_team(server):
    admin = login(server, "admin")
    team = admin.post("/admin/teams", json={"name": "Другая команда"}).json()
    outsider = admin.post(
        "/admin/users",
        json={"username": "outsider", "full_name": "Чужой", "role": "manager", "password": PASSWORD, "team_id": team["id"]},
    ).json()
    assert login(server, "lead1").get(f"/dashboard/managers/{outsider['id']}/sessions").status_code == 403
    assert admin.get(f"/dashboard/managers/{outsider['id']}/sessions").status_code == 200


# -------------------------------------------------------------- admin panel


@pytest.mark.parametrize("username", ["manager1", "lead1", "trainer1", "product1", "compliance1"])
def test_user_admin_is_admin_only(server, username):
    client = login(server, username)
    assert client.get("/admin/users").status_code == 403
    assert client.post("/admin/teams", json={"name": "x"}).status_code == 403


def test_admin_user_lifecycle(server):
    admin = login(server, "admin")
    created = admin.post(
        "/admin/users", json={"username": "newbie", "full_name": "Новый", "role": "manager", "password": "secret-123"}
    )
    assert created.status_code == 200
    assert admin.post(
        "/admin/users", json={"username": "newbie", "full_name": "Дубль", "role": "manager", "password": "secret-123"}
    ).status_code == 409
    assert admin.post(
        "/admin/users", json={"username": "short", "full_name": "x", "role": "manager", "password": "123"}
    ).status_code == 422
    login(server, "newbie", "secret-123")

    user_id = created.json()["id"]
    edit = {"full_name": "Новый", "role": "manager", "team_id": None, "is_active": False}
    assert admin.put(f"/admin/users/{user_id}", json=edit).status_code == 200
    response = TestClient(app).post("/auth/login", json={"username": "newbie", "password": "secret-123"})
    assert response.status_code == 401


def test_admin_cannot_lock_themselves_out(server):
    admin = login(server, "admin")
    me = admin.get("/auth/me").json()
    edit = {"full_name": "x", "role": "manager", "team_id": None, "is_active": True}
    assert admin.put(f"/admin/users/{me['id']}", json=edit).status_code == 400


@pytest.mark.parametrize("username,status", [("admin", 200), ("compliance1", 200), ("manager1", 403), ("trainer1", 403)])
def test_audit_log_access(server, scored_session, username, status):
    response = login(server, username).get("/admin/audit")
    assert response.status_code == status
    if status == 200:
        assert "session.scored" in {row["action"] for row in response.json()}


# ------------------------------------------------------------ scoring budget


def test_slow_scoring_ends_as_retryable_error(server, monkeypatch):
    import asyncio

    import app.main as main

    original = main.scoring_provider.verify_claims

    async def slow_verify_claims(*args, **kwargs):
        await asyncio.sleep(5)
        return await original(*args, **kwargs)

    manager = login(server, "manager2")
    session_id = manager.post("/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    manager.post(f"/sessions/{session_id}/turns", json={"text": "Добрый день!"})
    manager.post(f"/sessions/{session_id}/finish")

    monkeypatch.setattr(main, "_SCORING_BUDGET_SECONDS", 0.2)
    monkeypatch.setattr(main.scoring_provider, "verify_claims", slow_verify_claims)
    assert manager.post(f"/sessions/{session_id}/score-run").json()["status"] == "finish_error"
    assert manager.get(f"/sessions/{session_id}/score").json()["status"] == "finish_error"

    monkeypatch.undo()
    assert manager.post(f"/sessions/{session_id}/finish").json()["status"] == "scoring"
    assert manager.post(f"/sessions/{session_id}/score-run").json()["status"] == "finished"


# ------------------------------------------------------------ topics, themes


def test_catalog_returns_topics(server):
    scenario = login(server, "manager1").get("/scenarios").json()[0]
    assert {"id": "objections", "name": "Работа с возражениями"} in scenario["topics"]


def test_admin_meta_lists_topics(server):
    topics = login(server, "trainer1").get("/admin/meta").json()["topics"]
    assert topics["pressure_honesty"] == "Давление клиента и честные условия"


def test_every_seed_scenario_is_tagged(server):
    for scenario in login(server, "admin").get("/admin/scenarios").json():
        assert scenario["topics"], scenario["id"]


def _draft_data(client, scenario_id):
    item = next(s for s in client.get("/admin/scenarios").json() if s["id"] == scenario_id)
    version = item["versions"][-1]["version"]
    return client.get(f"/admin/scenarios/{scenario_id}/versions/{version}").json()["data"]


def test_scenario_topics_validated_and_saved(server):
    trainer = login(server, "trainer1")
    data = _draft_data(trainer, "scn_loan_easy_01")
    bad = trainer.put("/admin/scenarios/scn_loan_easy_01", json={"data": {**data, "topics": ["no_such_topic"]}})
    assert bad.status_code == 422
    ok = trainer.put("/admin/scenarios/scn_loan_easy_01", json={"data": {**data, "topics": ["objections", "objections"]}})
    assert ok.status_code == 200
    assert _draft_data(trainer, "scn_loan_easy_01")["topics"] == ["objections"]


def test_topics_backfilled_for_old_versions_only(server):
    """Versions stored before topics existed get the seed tags on the next
    init_db; a version whose topics were set (even emptied) is left alone."""
    import asyncio

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.main import init_db
    from app.models import ScenarioVersion

    async def strip_and_reinit():
        async with SessionLocal() as db:
            rows = (await db.execute(select(ScenarioVersion).where(ScenarioVersion.scenario_id.in_(
                [SCENARIO, "scn_rko_easy_01"])))).scalars().all()
            for row in rows:
                if row.scenario_id == SCENARIO:
                    row.data = {k: v for k, v in row.data.items() if k != "topics"}
                else:
                    row.data = {**row.data, "topics": []}
            await db.commit()
        await init_db()
        async with SessionLocal() as db:
            rows = (await db.execute(select(ScenarioVersion))).scalars().all()
            return {r.scenario_id: r.data.get("topics") for r in rows}

    topics = asyncio.run(strip_and_reinit())
    assert topics[SCENARIO] == ["objections", "competitor_switch"]
    assert topics["scn_rko_easy_01"] == []


def test_theme_script_served(server):
    response = server.get("/static/theme.js")
    assert response.status_code == 200
    assert "applyTheme" in response.text
