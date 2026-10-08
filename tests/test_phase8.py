"""Phase 8 — compliance, admin and pilot polish.

Work queue (a view over can_transition; no new approval policy), audit
filters and safe details, management analytics limited to managers'
sessions, disputes without score mutation or new transcript access, user
administration, and the frontend contracts of the new screens.
"""

import json
import re
from pathlib import Path

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    archive_published_scenarios,
    finish_and_score,
    kb_data,
    login,
    new_product,
    new_team_with_users,
    ok,
    publish_kb,
    say,
    scenario_data,
    server,
    start_session,
    uid,
)

from app.content import can_transition  # noqa: F401  (documented source of truth)

STATIC = Path(__file__).resolve().parent.parent / "static"


def queue(username):
    return ok(login(username).get("/admin/queue"))["items"]


def find(items, kind, item_id, version):
    return next((i for i in items if i["kind"] == kind and i["id"] == item_id and str(i["version"]) == str(version)), None)


# ------------------------------------------------------------ work queue


@pytest.fixture(scope="module")
def content(server):
    """A KB draft with a flagged entry, an approved clean KB, a scenario draft
    and an approved scenario whose product has no published KB."""
    flagged = new_product("p8f", publish=False, approved_facts=[{"id": "fact_x", "text": "Синтетический факт", "needs_review": True}])
    clean = new_product("p8c", publish=False)
    ok(login("compliance1").post(f"/admin/kb/{clean}/versions/1.0.0/status", json={"status": "approved"}))
    live = uid("p8l")
    publish_kb(live, "1.0.0", kb_data(live))
    trainer = login("trainer1")
    draft = ok(trainer.post("/admin/scenarios", json={"data": scenario_data(live)}))["id"]
    approved_no_kb = ok(trainer.post("/admin/scenarios", json={"data": scenario_data(clean)}))["id"]
    ok(login("product1").post(f"/admin/scenarios/{approved_no_kb}/versions/1/status", json={"status": "approved"}))
    return {"flagged": flagged, "clean": clean, "draft": draft, "approved_no_kb": approved_no_kb}


def test_queue_steps_follow_existing_lifecycle_per_role(content):
    compliance, product, trainer, admin = (queue(u) for u in ("compliance1", "product1", "trainer1", "admin"))
    # KB approve: compliance/admin; KB publish: product/admin
    assert find(compliance, "kb", content["flagged"], "1.0.0")["steps"] == ["approved"]
    assert find(product, "kb", content["clean"], "1.0.0")["steps"] == ["published"]
    assert find(compliance, "kb", content["clean"], "1.0.0") is None  # compliance cannot publish
    # Scenario approve: product/compliance/admin; publish: training/admin
    assert find(product, "scenario", content["draft"], 1)["steps"] == ["approved"]
    assert find(trainer, "scenario", content["approved_no_kb"], 1)["steps"] == ["published"]
    assert find(trainer, "scenario", content["draft"], 1) is None
    assert find(admin, "kb", content["clean"], "1.0.0")["steps"] == ["published"]
    for items in (compliance, product, trainer, admin):
        for item in items:
            assert set(item["steps"]) <= {"approved", "published"}  # never archive / revert as "work"
            assert item["status"] in ("draft", "approved")


def test_queue_shows_existing_guards_as_blocked(content):
    flagged = find(queue("compliance1"), "kb", content["flagged"], "1.0.0")
    assert flagged["blocked"]["code"] == "kb_unreviewed"
    assert flagged["review_blockers"] == [{"section": "approved_facts", "id": "fact_x"}]
    assert find(queue("trainer1"), "scenario", content["approved_no_kb"], 1)["blocked"]["code"] == "no_published_kb"
    # The guard itself is unchanged: approving the flagged draft is still refused.
    response = login("compliance1").post(f"/admin/kb/{content['flagged']}/versions/1.0.0/status", json={"status": "approved"})
    assert response.status_code == 409 and response.json()["code"] == "kb_unreviewed"


def test_queue_kb_drafts_with_blockers_visible_to_kb_editors(content):
    item = find(queue("product1"), "kb", content["flagged"], "1.0.0")  # product edits KB, cannot approve
    assert item["steps"] == [] and item["review_blockers"]


@pytest.mark.parametrize("username,status", [("manager1", 403), ("lead1", 403), ("trainer1", 200), ("product1", 200), ("compliance1", 200), ("admin", 200)])
def test_queue_access(server, username, status):
    assert login(username).get("/admin/queue").status_code == status


def test_queue_holds_metadata_only(content):
    text = json.dumps(queue("admin"), ensure_ascii=False)
    for field in ("client_profile", "approved_response", "hidden_need", "transcript", '"approved_facts": [', '"text":'):
        assert field not in text


def test_real_merchant_published_kb_is_not_a_queue_item_and_stays_c9(server):
    """C-9 is not special-cased: the published 1.0.0 has no next step, so it
    is not queue work; it is resolved through a new version."""
    for username in ("compliance1", "product1", "admin"):
        assert find(queue(username), "kb", "merchant_onboarding", "1.0.0") is None
    taxes = next(o for o in ok(login("admin").get("/admin/kb/merchant_onboarding/versions/1.0.0"))["data"]["objections"] if o["id"] == "obj_taxes")
    assert not taxes.get("needs_review")  # unresolved in content — still a bank item


def test_no_hardcoded_content_in_frontend():
    for path in (STATIC / "js").rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert "obj_taxes" not in text and "merchant_onboarding" not in text, path.name


# ------------------------------------------------------------ audit


def test_audit_filters(server):
    team = new_team_with_users({"m": "manager"})
    admin = login("admin")
    uid_ = ok(login(team["m"]).get("/auth/me"))["id"]
    rows = ok(admin.get(f"/admin/audit?entity_id={uid_}&action=user.create"))
    assert len(rows) == 1 and rows[0]["details"]["username"] == team["m"]
    assert all(r["actor"] and "admin" in r["actor"] for r in ok(admin.get("/admin/audit?actor=dmi&limit=20")))
    assert all(r["action"] == "auth.login" for r in ok(admin.get("/admin/audit?action=auth.login&limit=20")))


def test_user_edit_audit_records_old_and_new_values_without_password(server):
    team = new_team_with_users({"m": "manager"})
    admin = login("admin")
    target = ok(login(team["m"]).get("/auth/me"))
    ok(admin.put(f"/admin/users/{target['id']}", json={"full_name": "x", "role": "sales_lead", "team_id": target["team_id"], "is_active": False, "password": "SENTINEL_PASSWORD_P8"}))
    row = ok(admin.get(f"/admin/audit?entity_id={target['id']}&action=user.edit"))[0]
    assert row["details"]["role"] == {"from": "manager", "to": "sales_lead"}
    assert row["details"]["is_active"] == {"from": True, "to": False}
    assert row["details"]["password"] == "reset"
    everything = admin.get("/admin/audit?limit=1000").text
    assert "SENTINEL_PASSWORD_P8" not in everything and "demo12345" not in everything


@pytest.mark.parametrize("username,status", [("admin", 200), ("compliance1", 200), ("trainer1", 403), ("product1", 403), ("lead1", 403), ("manager1", 403)])
def test_audit_access(server, username, status):
    assert login(username).get("/admin/audit?action=auth.login").status_code == status


# ------------------------------------------------------------ management analytics scope


def test_org_dashboard_counts_only_manager_sessions(server):
    pid = uid("p8a")
    publish_kb(pid, "1.0.0", kb_data(pid))
    trainer = login("trainer1")
    sid = ok(trainer.post("/admin/scenarios", json={"data": scenario_data(pid)}))["id"]
    ok(login("product1").post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}))
    ok(trainer.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}))
    team = new_team_with_users({"m": "manager", "lead": "sales_lead", "t": "training", "a": "admin"})
    for key in ("m", "lead", "t", "a"):
        client = login(team[key])
        session = start_session(client, sid)
        say(client, session["id"])
        finish_and_score(client, session["id"])
    for viewer in ("admin", "trainer1", "product1", "compliance1"):
        kpi = ok(login(viewer).get(f"/dashboard/data?days=0&product_id={pid}"))["kpi"]
        assert (kpi["sessions_started"], kpi["sessions_scored"]) == (1, 1), viewer
    team_kpi = ok(login(team["lead"]).get(f"/dashboard/data?days=0&product_id={pid}"))["kpi"]
    assert team_kpi["sessions_started"] == 1


def test_deactivated_manager_behaviour_is_as_documented(server):
    """Team view: roster and team numbers cover active managers only.
    Org-wide view: a deactivated manager's past sessions still count.
    Nothing is deleted; the lead can still open the history by URL."""
    pid = uid("p8d")
    publish_kb(pid, "1.0.0", kb_data(pid))
    trainer = login("trainer1")
    sid = ok(trainer.post("/admin/scenarios", json={"data": scenario_data(pid)}))["id"]
    ok(login("product1").post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}))
    ok(trainer.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}))
    team = new_team_with_users({"m": "manager", "lead": "sales_lead"})
    client = login(team["m"])
    session = start_session(client, sid)
    say(client, session["id"])
    finish_and_score(client, session["id"])
    me = ok(client.get("/auth/me"))
    ok(login("admin").put(f"/admin/users/{me['id']}", json={"full_name": me["full_name"], "role": "manager", "team_id": me["team_id"], "is_active": False}))
    lead = login(team["lead"])
    assert ok(lead.get(f"/dashboard/data?days=0&product_id={pid}"))["kpi"]["sessions_started"] == 0
    assert ok(lead.get(f"/dashboard/data?days=0"))["managers"] == []
    assert ok(login("admin").get(f"/dashboard/data?days=0&product_id={pid}"))["kpi"]["sessions_started"] == 1
    assert len(ok(lead.get(f"/dashboard/managers/{me['id']}/sessions"))["sessions"]) == 1


# ------------------------------------------------------------ disputes


def test_dispute_is_recorded_without_score_change_and_without_new_access(server):
    team = new_team_with_users({"m": "manager", "lead": "sales_lead"})
    other = new_team_with_users({"lead": "sales_lead"})
    client = login(team["m"])
    session = start_session(client, "scn_merchant_onboarding_medium_01")
    say(client, session["id"])
    before = finish_and_score(client, session["id"])
    ok(client.post(f"/sessions/{session['id']}/dispute", json={"comment": "Не согласен с оценкой DISPUTE_P8"}))
    after = ok(client.get(f"/sessions/{session['id']}/score"))
    assert after["total"] == before["total"] and after["breakdown"] == before["breakdown"]
    assert after["dispute"]["comment"] == "Не согласен с оценкой DISPUTE_P8"
    # Own lead sees it with the session link; another team's lead does not.
    own = ok(login(team["lead"]).get("/dashboard/data?days=0"))["disputes"]
    assert any(d["session_id"] == session["id"] for d in own)
    assert all(d["session_id"] != session["id"] for d in ok(login(other["lead"]).get("/dashboard/data?days=0"))["disputes"])
    # Compliance: no dispute list, no transcript (unchanged; pending bank decision B-2).
    assert ok(login("compliance1").get("/dashboard/data?days=0"))["disputes"] == []
    assert login("compliance1").get(f"/sessions/{session['id']}/transcript").status_code == 403
    # Training sees disputes without names (aggregate role, existing behaviour).
    training = [d for d in ok(login("trainer1").get("/dashboard/data?days=0"))["disputes"] if d["session_id"] == session["id"]]
    assert training and training[0]["full_name"] is None
    assert login("trainer1").get(f"/sessions/{session['id']}/transcript").status_code == 403


def test_only_the_owner_can_dispute(server):
    team = new_team_with_users({"m": "manager", "lead": "sales_lead"})
    client = login(team["m"])
    session = start_session(client, "scn_merchant_onboarding_medium_01")
    say(client, session["id"])
    finish_and_score(client, session["id"])
    for username in (team["lead"], "admin", "compliance1"):
        assert login(username).post(f"/sessions/{session['id']}/dispute", json={"comment": "x"}).status_code == 403


# ------------------------------------------------------------ users


@pytest.mark.parametrize("username", ["manager1", "lead1", "trainer1", "product1", "compliance1"])
def test_user_administration_is_admin_only(server, username):
    client = login(username)
    assert client.get("/admin/users").status_code == 403
    assert client.post("/admin/users", json={"username": uid("x"), "full_name": "x", "role": "admin", "password": "12345678"}).status_code == 403
    assert client.get("/admin/teams").status_code == 403


def test_no_self_registration_route(server):
    from fastapi.testclient import TestClient

    from app.main import app

    anonymous = TestClient(app)
    for path in ("/auth/register", "/auth/signup", "/register", "/signup"):
        assert anonymous.post(path, json={"username": "x", "password": "12345678"}).status_code in (404, 405)
    assert anonymous.post("/admin/users", json={"username": "x", "full_name": "x", "role": "admin", "password": "12345678"}).status_code == 401


def test_admin_cannot_lock_themselves_out(server):
    admin = login("admin")
    me = ok(admin.get("/auth/me"))
    assert admin.put(f"/admin/users/{me['id']}", json={"full_name": "a", "role": "admin", "team_id": None, "is_active": False}).status_code == 400
    assert admin.put(f"/admin/users/{me['id']}", json={"full_name": "a", "role": "manager", "team_id": None, "is_active": True}).status_code == 400


def test_deactivated_user_cannot_log_in(server):
    team = new_team_with_users({"m": "manager"})
    me = ok(login(team["m"]).get("/auth/me"))
    ok(login("admin").put(f"/admin/users/{me['id']}", json={"full_name": "x", "role": "manager", "team_id": me["team_id"], "is_active": False}))
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).post("/auth/login", json={"username": team["m"], "password": "demo12345"}).status_code == 401


# ------------------------------------------------------------ frontend contracts


def js(path):
    return (STATIC / path).read_text(encoding="utf-8")


def test_queue_page_uses_only_scoped_endpoints(server):
    assert '<script src="/static/js/pages/queue.js"></script>' in login("compliance1").get("/queue").text
    calls = set(re.findall(r"api\(['`]([^'`?]+)", js("js/pages/queue.js")))
    assert calls == {"/admin/queue", "/admin/audit"}
    assert "can_transition" in js("js/pages/queue.js") and "не отдельная процедура согласования" in js("js/pages/queue.js")


def test_admin_user_changes_are_confirmed_and_audit_links_respect_roles():
    admin = js("js/pages/admin.js")
    assert "confirmDialog({" in admin and "Отключить вход" in admin and "Роль:" in admin and "Команда:" in admin
    assert "entity_type === 'session' && me.role === 'admin'" in admin  # compliance gets no dead session links
    assert "JSON.stringify(r.details)" not in admin  # readable details, not raw JSON


def test_refused_session_page_shows_one_clear_state():
    page = js("session.html")
    assert 'id="transcript-panel"' in page and 'class="panel hidden" id="transcript-panel"' in page
    script = js("js/pages/session.js")
    assert "Разбор недоступен" in script and "classList.remove('hidden')" in script


def test_compliance_and_product_land_on_their_work_queue():
    assert "product: '/queue', compliance: '/queue'" in js("js/pages/login.js")
