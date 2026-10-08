"""Phase 5B — GET /me/progress: the caller's own, deterministic training
analytics from stored data. Each test uses fresh users and controlled
(stubbed) scoring output so expected numbers are exact.
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


def uniform(pct):
    return [{"criterion_id": c, "score": pct, "max": 100} for c in CRITERIA]


@pytest.fixture
def scored(monkeypatch):
    """Runs one fully scored session with the given stored outcome."""

    def run(username, breakdown, critical=(), claims=(), next_skill=None, scenario=SEED, text="Добрый день!"):
        async def verify_claims(transcript, kb):
            return [dict(c) for c in claims]

        async def score(transcript, rubric, claim_checks):
            return {
                "breakdown": [dict(b) for b in breakdown],
                "critical_errors": [dict(e) for e in critical],
                "feedback": {"summary": "s", "strengths": [], "growth_areas": [], "better_examples": [], "next_skill": next_skill},
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


def manager():
    return new_team_with_users({"m": "manager"})["m"]


def progress(username, query=""):
    return ok(login(username).get("/me/progress" + query))


CRITICAL = {"type": "Гарантия, которой нет в утверждённых материалах.", "quote": "q", "explanation": "e"}


def claim(verdict, turn=1):
    return {"claim_text": f"утверждение {verdict}", "turn_index": turn, "verdict": verdict, "matched_entry_id": None, "reason": "r"}


# ------------------------------------------------------------ basics


def test_empty_manager_gets_truthful_empty_progress(server):
    data = progress(manager())
    assert data == {
        "sessions": {"scored": 0, "in_progress": 0, "scoring": 0, "scoring_failed": 0},
        "summary": {"average_score": None, "latest_score": None, "latest_at": None, "first_score": None},
        "score_trend": [],
        "criteria": [],
        "weakest_criterion": None,
        "strongest_criterion": None,
        "products": [],
        "compliance": {"critical_errors": 0, "sessions_with_critical_errors": 0, "claims": {"approved": 0, "unapproved": 0, "forbidden": 0}},
        "next_skill": None,
    }


def test_one_session(server, scored):
    user = manager()
    session_id = scored(user, uniform(70))
    data = progress(user)
    assert data["sessions"]["scored"] == 1
    assert data["summary"]["average_score"] == data["summary"]["latest_score"] == data["summary"]["first_score"] == 70
    assert [p["session_id"] for p in data["score_trend"]] == [session_id]
    assert all(c["avg_pct"] == 70 and c["samples"] == 1 for c in data["criteria"])


def test_multiple_sessions_average_latest_trend(server, scored):
    user = manager()
    ids = [scored(user, uniform(p)) for p in (41, 42, 44)]
    data = progress(user)
    assert data["summary"]["average_score"] == 42.3  # (41 + 42 + 44) / 3, 1 decimal
    assert (data["summary"]["first_score"], data["summary"]["latest_score"]) == (41, 44)
    assert [p["session_id"] for p in data["score_trend"]] == ids  # chronological
    assert [p["total"] for p in data["score_trend"]] == [41, 42, 44]


def test_capped_score_counts_as_stored_final_score(server, scored):
    user = manager()
    scored(user, uniform(90), critical=[CRITICAL])
    data = progress(user)
    assert data["summary"]["latest_score"] == 60 and data["score_trend"][0]["total"] == 60
    assert data["score_trend"][0]["critical_errors"] == 1


def test_unfinished_and_failed_sessions_are_excluded_but_counted(server, scored, monkeypatch):
    user = manager()
    scored(user, uniform(50))
    client = login(user)
    active = start_session(client, SEED)["id"]  # active
    say(client, active)
    scoring = start_session(client, SEED)["id"]  # scoring, never run
    say(client, scoring)
    ok(client.post(f"/sessions/{scoring}/finish"))

    async def fail(*args, **kwargs):
        raise RuntimeError("SECRET_PROVIDER_ERROR_5B")

    failed = start_session(client, SEED)["id"]
    say(client, failed)
    monkeypatch.setattr(main.scoring_provider, "verify_claims", fail)
    ok(client.post(f"/sessions/{failed}/finish"))
    assert ok(client.post(f"/sessions/{failed}/score-run"))["status"] == "finish_error"

    response = login(user).get("/me/progress")
    data = response.json()
    assert data["sessions"] == {"scored": 1, "in_progress": 1, "scoring": 1, "scoring_failed": 1}
    assert data["summary"]["average_score"] == 50 and len(data["score_trend"]) == 1
    assert "SECRET_PROVIDER_ERROR" not in response.text


# ------------------------------------------------------------ criteria


def test_criteria_normalised_by_their_own_maximum(server, scored):
    """Raw points would rank needs (10 pts) above contact (9 pts); normalised,
    contact (90%) is stronger than needs (10/15 = 67%)."""
    user = manager()
    scored(user, [{"criterion_id": "contact", "score": 9, "max": 10}, {"criterion_id": "needs", "score": 10, "max": 15}])
    data = progress(user)
    by_id = {c["criterion_id"]: c for c in data["criteria"]}
    assert (by_id["contact"]["avg_pct"], by_id["needs"]["avg_pct"]) == (90, 67)
    assert data["weakest_criterion"]["criterion_id"] == "needs"
    assert data["strongest_criterion"]["criterion_id"] == "contact"
    assert [c["criterion_id"] for c in data["criteria"]] == ["needs", "contact"]  # weakest first
    assert by_id["contact"]["name"] == "Установление контакта"


def test_criterion_mean_is_per_session_ratio(server, scored):
    user = manager()
    scored(user, [{"criterion_id": "needs", "score": 15, "max": 15}, {"criterion_id": "contact", "score": 0, "max": 10}])
    scored(user, [{"criterion_id": "needs", "score": 0, "max": 15}, {"criterion_id": "contact", "score": 10, "max": 10}])
    by_id = {c["criterion_id"]: c for c in progress(user)["criteria"]}
    assert by_id["needs"]["avg_pct"] == by_id["contact"]["avg_pct"] == 50 and by_id["needs"]["samples"] == 2


def test_ties_resolved_by_rubric_order(server, scored):
    user = manager()
    scored(user, [{"criterion_id": "needs", "score": 5, "max": 10}, {"criterion_id": "contact", "score": 5, "max": 10}, {"criterion_id": "value", "score": 5, "max": 10}])
    data = progress(user)
    # rubric order: contact, needs, …, value — the earlier criterion wins both ties
    assert data["weakest_criterion"]["criterion_id"] == "contact"
    assert data["strongest_criterion"]["criterion_id"] == "contact"
    assert [c["criterion_id"] for c in data["criteria"]] == ["contact", "needs", "value"]


def test_single_criterion_has_no_separate_strongest(server, scored):
    user = manager()
    scored(user, [{"criterion_id": "needs", "score": 5, "max": 10}])
    data = progress(user)
    assert data["weakest_criterion"]["criterion_id"] == "needs" and data["strongest_criterion"] is None


# ------------------------------------------------------------ products, compliance, next_skill


def test_products_grouped_by_bound_version_even_after_republish(server, scored):
    user = manager()
    product_a, product_b = new_product("p5ba"), new_product("p5bb")
    scenario_id = published_scenario(product_a, difficulty="easy")
    scored(user, uniform(40), scenario=scenario_id)
    ok(login("trainer1").put(f"/admin/scenarios/{scenario_id}", json={"data": scenario_data(product_b, difficulty="hard")}))
    approve_and_publish_scenario(scenario_id, 2)
    scored(user, uniform(80), scenario=scenario_id)
    products = {p["product_id"]: p for p in progress(user)["products"]}
    assert (products[product_a]["sessions"], products[product_a]["avg_score"]) == (1, 40)
    assert (products[product_b]["sessions"], products[product_b]["avg_score"]) == (1, 80)
    assert [p["product_id"] for p in progress(user)["products"]] == [product_a, product_b]  # weakest first


def test_critical_errors_and_claim_counts(server, scored):
    user = manager()
    scored(user, uniform(90), critical=[CRITICAL, CRITICAL], claims=[claim("approved"), claim("unapproved")])
    scored(user, uniform(90), critical=[CRITICAL], claims=[claim("forbidden"), claim("approved")])
    scored(user, uniform(70), claims=[claim("approved")])
    data = progress(user)
    assert data["compliance"] == {
        "critical_errors": 3,
        "sessions_with_critical_errors": 2,
        "claims": {"approved": 3, "unapproved": 1, "forbidden": 1},
    }


def test_next_skill_is_latest_evaluator_feedback(server, scored):
    user = manager()
    scored(user, uniform(50), next_skill="Работа с возражениями")
    second = scored(user, uniform(60), next_skill="Выявление потребностей")
    scored(user, uniform(70), next_skill=None)  # latest has none → keep the latest that has one
    skill = progress(user)["next_skill"]
    assert skill["text"] == "Выявление потребностей" and skill["session_id"] == second
    assert skill["source"] == "evaluator_feedback"


def test_missing_next_skill_is_null(server, scored):
    user = manager()
    scored(user, uniform(50), next_skill=None)
    assert progress(user)["next_skill"] is None


# ------------------------------------------------------------ privacy


def test_only_the_callers_sessions_and_no_selection_parameter(server, scored):
    team = new_team_with_users({"a": "manager", "b": "manager"})
    scored(team["a"], uniform(30))
    other = scored(team["b"], uniform(95))
    b_id = ok(login(team["b"]).get("/auth/me"))["id"]
    for query in ("", f"?user_id={b_id}", f"?manager_id={b_id}", f"?username={team['b']}", "?team_id=1"):
        data = progress(team["a"], query)
        assert data["sessions"]["scored"] == 1 and data["summary"]["average_score"] == 30, query
        assert other not in str(data)


@pytest.mark.parametrize("username,status", [("manager1", 200), ("lead1", 200), ("trainer1", 200), ("admin", 200), ("product1", 403), ("compliance1", 403)])
def test_roles(server, username, status):
    assert login(username).get("/me/progress").status_code == status


def test_no_transcript_hidden_fields_or_raw_data(server, scored):
    user = manager()
    hidden = ok(login("admin").get(f"/admin/scenarios/{SEED}/versions/1"))["data"]["client_profile"]
    scored(user, uniform(80), critical=[CRITICAL], claims=[claim("unapproved")], text="TRANSCRIPT_SENTINEL_5B фраза менеджера")
    text = login(user).get("/me/progress").text
    assert "TRANSCRIPT_SENTINEL_5B" not in text
    for key in ("pain", "hidden_need", "decision_criteria"):
        value = hidden.get(key)
        if isinstance(value, str) and len(value) > 8:
            assert value not in text, key
    for field in ("client_profile", "transcript", "claim_text", "quote", "explanation", "breakdown", "password", "username"):
        assert f'"{field}"' not in text, field
