"""Phase 6 — Sales Lead experience.

Access: a lead's individual-data scope is users with the manager role on the
lead's own team (Decision 1); the new GET /dashboard/managers/{id}/progress
follows the same rule. Analytics: factual per-manager indicators in
alphabetical order, no thresholds/classification (Decision 2), the shared
criterion rule (Decision 4) and bound-version products.
"""

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    CRITERIA,
    approve_and_publish_scenario,
    archive_published_scenarios,
    login,
    new_product,
    new_team_with_users,
    ok,
    published_scenario,
    say,
    scenario_data,
    server,
    start_session,
    uid,
)

import app.main as main

SEED = "scn_merchant_onboarding_medium_01"
CRITICAL = {"type": "Гарантия, которой нет в утверждённых материалах.", "quote": "q", "explanation": "e"}


def uniform(pct):
    return [{"criterion_id": c, "score": pct, "max": 100} for c in CRITERIA]


def claim(verdict):
    return {"claim_text": f"утверждение {verdict}", "turn_index": 1, "verdict": verdict, "matched_entry_id": None, "reason": "r"}


@pytest.fixture
def scored(monkeypatch):
    """Runs one fully scored session for `username` with a controlled outcome."""

    def run(username, breakdown=None, critical=(), claims=(), scenario=SEED, text="Добрый день!"):
        async def verify_claims(transcript, kb):
            return [dict(c) for c in claims]

        async def score(transcript, rubric, claim_checks):
            return {
                "breakdown": [dict(b) for b in (breakdown or uniform(50))],
                "critical_errors": [dict(e) for e in critical],
                "feedback": {"summary": "s", "strengths": [], "growth_areas": [], "better_examples": [], "next_skill": "Навык"},
            }

        monkeypatch.setattr(main.scoring_provider, "verify_claims", verify_claims)
        monkeypatch.setattr(main.scoring_provider, "score", score)
        client = login(username)
        session_id = start_session(client, scenario)["id"]
        say(client, session_id, text)
        ok(client.post(f"/sessions/{session_id}/finish"))
        assert ok(client.post(f"/sessions/{session_id}/score-run"))["status"] == "finished"
        return session_id

    return run


def user_id(username):
    return ok(login(username).get("/auth/me"))["id"]


def team_data(lead, query="?days=0"):
    return ok(login(lead).get("/dashboard/data" + query))


# ------------------------------------------------------------ privacy matrix (Decision 1)


@pytest.fixture
def two_teams(server, scored):
    a = new_team_with_users({"manager": "manager", "lead": "sales_lead", "lead2": "sales_lead", "trainer": "training",
                             "product": "product", "compliance": "compliance", "admin": "admin"})
    b = new_team_with_users({"manager": "manager", "lead": "sales_lead"})
    sessions = {}
    for key, team in (("a_manager", a["manager"]), ("a_lead2", a["lead2"]), ("a_trainer", a["trainer"]), ("a_admin", a["admin"]), ("b_manager", b["manager"])):
        sessions[key] = scored(team, text="SENTINEL_TRANSCRIPT_" + key)
    return {"a": a, "b": b, "sessions": sessions}


SESSION_ROUTES = ("/sessions/{}/score", "/sessions/{}/transcript")
DRILL_ROUTES = ("/dashboard/managers/{}/sessions", "/dashboard/managers/{}/progress")


def test_lead_reaches_own_team_manager(two_teams):
    lead = login(two_teams["a"]["lead"])
    sid = two_teams["sessions"]["a_manager"]
    for route in SESSION_ROUTES:
        assert lead.get(route.format(sid)).status_code == 200, route
    assert "SENTINEL_TRANSCRIPT_a_manager" in lead.get(f"/sessions/{sid}/transcript").text  # existing policy
    for route in DRILL_ROUTES:
        assert lead.get(route.format(user_id(two_teams["a"]["manager"]))).status_code == 200, route


@pytest.mark.parametrize("key", ["b_manager", "a_lead2", "a_trainer", "a_admin"])
def test_lead_cannot_open_sessions_outside_manager_scope(two_teams, key):
    lead = login(two_teams["a"]["lead"])
    for route in SESSION_ROUTES:
        response = lead.get(route.format(two_teams["sessions"][key]))
        assert response.status_code == 403, (key, route)
        assert "SENTINEL_TRANSCRIPT" not in response.text


@pytest.mark.parametrize("target", [("b", "manager"), ("b", "lead"), ("a", "lead2"), ("a", "trainer"), ("a", "product"), ("a", "compliance"), ("a", "admin"), ("a", "lead")])
def test_lead_cannot_drill_into_non_managers_or_other_teams(two_teams, target):
    lead = login(two_teams["a"]["lead"])
    target_id = user_id(two_teams[target[0]][target[1]])
    for route in DRILL_ROUTES:
        response = lead.get(route.format(target_id))
        assert response.status_code == 403, (target, route)
        assert "SENTINEL_TRANSCRIPT" not in response.text


def test_admin_access_unchanged(two_teams):
    admin = login("admin")
    for key, sid in two_teams["sessions"].items():
        for route in SESSION_ROUTES:
            assert admin.get(route.format(sid)).status_code == 200, (key, route)
    for team, role in (("a", "manager"), ("b", "manager"), ("a", "lead2"), ("a", "trainer")):
        for route in DRILL_ROUTES:
            assert admin.get(route.format(user_id(two_teams[team][role]))).status_code == 200


def test_owner_access_unchanged(two_teams):
    for key, username in (("a_lead2", two_teams["a"]["lead2"]), ("a_trainer", two_teams["a"]["trainer"]), ("b_manager", two_teams["b"]["manager"])):
        for route in SESSION_ROUTES:
            assert login(username).get(route.format(two_teams["sessions"][key])).status_code == 200


@pytest.mark.parametrize("role", ["manager", "training", "product", "compliance"])
def test_other_roles_cannot_use_drilldown(two_teams, role):
    username = {"manager": "manager1", "training": "trainer1", "product": "product1", "compliance": "compliance1"}[role]
    for route in DRILL_ROUTES:
        assert login(username).get(route.format(user_id(two_teams["a"]["manager"]))).status_code == 403


def test_unknown_manager_is_404(server):
    for route in DRILL_ROUTES:
        assert login("lead1").get(route.format("no-such-user")).status_code == 404


def test_team_dashboard_contains_only_team_managers(two_teams):
    a, b = two_teams["a"], two_teams["b"]
    b_team = ok(login(b["lead"]).get("/auth/me"))["team_id"]
    for query in ("?days=0", f"?days=0&team_id={b_team}"):
        data = team_data(a["lead"], query)
        assert [m["full_name"] for m in data["managers"]] == [a["manager"]]
        assert {r["id"] for r in data["recent_sessions"]} == {two_teams["sessions"]["a_manager"]}
        assert data["kpi"]["sessions_scored"] == 1  # lead2/trainer/admin/Team B sessions excluded
        text = str(data)
        for key in ("b_manager", "a_lead2", "a_trainer", "a_admin"):
            assert two_teams["sessions"][key] not in text, key
        assert b["manager"] not in text and a["lead2"] not in text


# ------------------------------------------------------------ factual indicators (Decision 2)


def test_managers_alphabetical_with_facts_and_no_classification(server, scored):
    # full_name = username = "<key>_<random>", so the keys fix the alphabetical order,
    # which deliberately differs from the score order.
    team = new_team_with_users({"lead": "sales_lead", "zeta": "manager", "alpha": "manager", "mid": "manager"})
    scored(team["zeta"], uniform(20))
    scored(team["alpha"], uniform(90))
    scored(team["alpha"], uniform(90), critical=[CRITICAL, CRITICAL])  # capped → 60
    data = team_data(team["lead"])
    rows = data["managers"]
    assert [r["full_name"] for r in rows] == [team["alpha"], team["mid"], team["zeta"]]
    alpha, mid, zeta = rows
    assert (alpha["scored"], alpha["avg_score"], alpha["last_score"]) == (2, 75, 60)
    assert (alpha["critical_errors"], alpha["sessions_with_critical_errors"], alpha["latest_has_critical_error"]) == (2, 1, True)
    assert (zeta["avg_score"], zeta["latest_has_critical_error"]) == (20, False)
    assert (mid["sessions"], mid["scored"], mid["avg_score"], mid["last_activity_at"], mid["weakest_skill"]) == (0, 0, None, None, None)
    for row in rows:
        for banned in ("needs_help", "reasons", "rank", "risk", "level", "percentile"):
            assert banned not in row
    assert "recommendations" not in data


def test_active_and_failed_sessions_counted_but_not_scored(server, scored, monkeypatch):
    team = new_team_with_users({"lead": "sales_lead", "m": "manager"})
    scored(team["m"], uniform(50))
    client = login(team["m"])
    active = start_session(client, SEED)["id"]
    say(client, active)

    async def fail(*args, **kwargs):
        raise RuntimeError("SECRET_PROVIDER_ERROR_P6")

    failed = start_session(client, SEED)["id"]
    say(client, failed)
    monkeypatch.setattr(main.scoring_provider, "verify_claims", fail)
    ok(client.post(f"/sessions/{failed}/finish"))
    ok(client.post(f"/sessions/{failed}/score-run"))
    response = login(team["lead"]).get("/dashboard/data?days=0")
    data = response.json()
    row = data["managers"][0]
    assert (row["sessions"], row["scored"], row["avg_score"]) == (3, 1, 50)
    assert {r["status"] for r in data["recent_sessions"]} == {"finished", "active", "finish_error"}
    assert "SECRET_PROVIDER_ERROR" not in response.text
    progress = ok(login(team["lead"]).get(f"/dashboard/managers/{user_id(team['m'])}/progress"))
    assert progress["sessions"] == {"scored": 1, "in_progress": 1, "scoring": 0, "scoring_failed": 1}


# ------------------------------------------------------------ shared criterion rule (Decision 4)


def test_manager_weakest_skill_uses_clamped_normalised_rule_with_rubric_ties(server, scored):
    team = new_team_with_users({"lead": "sales_lead", "m": "manager"})
    # needs: 10/15 = 67%; contact: 12/10 clamps to 100%; value 5/10 = 50% ties nothing.
    scored(team["m"], [{"criterion_id": "contact", "score": 12, "max": 10}, {"criterion_id": "needs", "score": 10, "max": 15}, {"criterion_id": "value", "score": 5, "max": 10}])
    row = team_data(team["lead"])["managers"][0]
    assert row["weakest_skill"] == {"criterion_id": "value", "name": row["weakest_skill"]["name"], "avg_pct": 50}
    team2 = new_team_with_users({"lead": "sales_lead", "m": "manager"})
    scored(team2["m"], [{"criterion_id": "value", "score": 5, "max": 10}, {"criterion_id": "contact", "score": 5, "max": 10}])
    assert team_data(team2["lead"])["managers"][0]["weakest_skill"]["criterion_id"] == "contact"  # earlier in rubric


def test_team_skills_normalised_and_weakest_matches_drilldown(server, scored):
    team = new_team_with_users({"lead": "sales_lead", "m": "manager"})
    scored(team["m"], [{"criterion_id": "contact", "score": 9, "max": 10}, {"criterion_id": "needs", "score": 10, "max": 15}])
    data = team_data(team["lead"])
    assert [(s["criterion_id"], s["avg_pct"]) for s in data["skills"]] == [("needs", 67), ("contact", 90)]
    assert data["weakest_skill"]["criterion_id"] == "needs"
    drill = ok(login(team["lead"]).get(f"/dashboard/managers/{user_id(team['m'])}/progress"))
    assert drill["weakest_criterion"]["criterion_id"] == data["managers"][0]["weakest_skill"]["criterion_id"] == "needs"


# ------------------------------------------------------------ drill-down = build_progress


def test_drilldown_progress_is_the_managers_own_progress(server, scored):
    team = new_team_with_users({"lead": "sales_lead", "m": "manager"})
    scored(team["m"], uniform(40), claims=[claim("approved"), claim("unapproved"), claim("forbidden")])
    scored(team["m"], uniform(90), critical=[CRITICAL])
    own = ok(login(team["m"]).get("/me/progress"))
    drill = ok(login(team["lead"]).get(f"/dashboard/managers/{user_id(team['m'])}/progress"))
    assert set(drill.pop("user")) == {"id", "full_name"}
    assert drill == own
    assert drill["summary"]["latest_score"] == 60  # capped stays official
    assert drill["compliance"]["claims"] == {"approved": 1, "unapproved": 1, "forbidden": 1}


def test_drilldown_and_team_view_have_no_transcript_or_hidden_fields(server, scored):
    team = new_team_with_users({"lead": "sales_lead", "m": "manager"})
    hidden = ok(login("admin").get(f"/admin/scenarios/{SEED}/versions/1"))["data"]["client_profile"]
    scored(team["m"], uniform(70), critical=[CRITICAL], claims=[claim("unapproved")], text="SENTINEL_P6_TRANSCRIPT")
    lead = login(team["lead"])
    mid = user_id(team["m"])
    for path in ("/dashboard/data?days=0", f"/dashboard/managers/{mid}/progress", f"/dashboard/managers/{mid}/sessions"):
        text = lead.get(path).text
        assert "SENTINEL_P6_TRANSCRIPT" not in text, path
        for key in ("pain", "hidden_need", "decision_criteria"):
            value = hidden.get(key)
            if isinstance(value, str) and len(value) > 8:
                assert value not in text, (path, key)
        for field in ("client_profile", "transcript", "claim_text", "password", "username"):
            assert f'"{field}"' not in text, (path, field)


# ------------------------------------------------------------ products & compliance


def test_team_products_follow_bound_version_after_republish(server, scored):
    team = new_team_with_users({"lead": "sales_lead", "m": "manager"})
    product_a, product_b = new_product("p6a"), new_product("p6b")
    scenario_id = published_scenario(product_a, difficulty="easy")
    old = scored(team["m"], uniform(40), scenario=scenario_id)
    ok(login("trainer1").put(f"/admin/scenarios/{scenario_id}", json={"data": scenario_data(product_b, difficulty="hard")}))
    approve_and_publish_scenario(scenario_id, 2)
    scored(team["m"], uniform(80), critical=[CRITICAL], scenario=scenario_id)
    data = team_data(team["lead"])
    products = {p["product_id"]: p for p in data["products"]}
    assert (products[product_a]["scored"], products[product_a]["avg_score"], products[product_a]["sessions_with_critical_errors"]) == (1, 40, 0)
    assert (products[product_b]["scored"], products[product_b]["avg_score"], products[product_b]["sessions_with_critical_errors"]) == (1, 60, 1)
    recent = {r["id"]: r for r in data["recent_sessions"]}
    assert (recent[old]["product_id"], recent[old]["difficulty"]) == (product_a, "easy")


def test_team_critical_and_claim_counts(server, scored):
    team = new_team_with_users({"lead": "sales_lead", "m1": "manager", "m2": "manager"})
    scored(team["m1"], uniform(90), critical=[CRITICAL, CRITICAL], claims=[claim("approved"), claim("unapproved")])
    scored(team["m2"], uniform(70), claims=[claim("forbidden"), claim("approved")])
    data = team_data(team["lead"])
    assert (data["kpi"]["critical_errors"], data["kpi"]["sessions_with_critical_errors"], data["kpi"]["sessions_scored"]) == (2, 1, 2)
    assert data["risks"]["claims"] == {"approved": 2, "unapproved": 1, "forbidden": 1}
    assert data["kpi"]["managers_trained"] == 2


# ------------------------------------------------------------ empty states


def test_team_without_managers(server):
    team = new_team_with_users({"lead": "sales_lead"})
    data = team_data(team["lead"])
    assert data["managers"] == [] and data["recent_sessions"] == [] and data["kpi"]["total_managers"] == 0
    assert data["kpi"]["avg_score"] is None and data["weakest_skill"] is None


def test_team_with_untrained_manager(server):
    team = new_team_with_users({"lead": "sales_lead", "m": "manager"})
    data = team_data(team["lead"])
    assert data["managers"][0]["sessions"] == 0 and data["kpi"]["managers_trained"] == 0
    drill = ok(login(team["lead"]).get(f"/dashboard/managers/{user_id(team['m'])}/progress"))
    assert drill["sessions"]["scored"] == 0 and drill["score_trend"] == []
