"""Fix: historical session metadata (title, product, difficulty) comes from
the session's BOUND scenario version — publishing a new version must never
reclassify history in /me/sessions, the lead drill-down or the dashboard.

Regression for the bug where product/difficulty were read from the
scenario's current published copy.
"""

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    approve_and_publish_scenario,
    archive_published_scenarios,
    finish_and_score,
    login,
    new_product,
    new_team_with_users,
    ok,
    published_scenario,
    say,
    scenario_data,
    server,
    start_session,
)


@pytest.fixture(scope="module")
def history(server):
    """Scenario v1 (product A, easy) → scored session; then v2 (product B, hard)
    published → a new session on v2."""
    people = new_team_with_users({"manager": "manager", "lead": "sales_lead"})
    product_a, product_b = new_product("hista"), new_product("histb")
    scenario_id = published_scenario(product_a, difficulty="easy", title="История v1")
    manager = login(people["manager"])
    old = start_session(manager, scenario_id)
    say(manager, old["id"])
    finish_and_score(manager, old["id"])

    ok(login("trainer1").put(f"/admin/scenarios/{scenario_id}", json={"data": scenario_data(product_b, difficulty="hard", title="История v2")}))
    approve_and_publish_scenario(scenario_id, 2)

    new = start_session(manager, scenario_id)
    say(manager, new["id"])
    finish_and_score(manager, new["id"])
    return {**people, "a": product_a, "b": product_b, "old": old, "new": new}


def _row(rows, session_id):
    return next(r for r in rows if r["id"] == session_id)


def test_session_start_responses_are_bound(history):
    assert (history["old"]["scenario_version"], history["old"]["product_id"], history["old"]["difficulty"]) == (1, history["a"], "easy")
    assert (history["new"]["scenario_version"], history["new"]["product_id"], history["new"]["difficulty"]) == (2, history["b"], "hard")


def test_manager_history_keeps_old_session_on_its_bound_version(history):
    rows = ok(login(history["manager"]).get("/me/sessions"))
    old, new = _row(rows, history["old"]["id"]), _row(rows, history["new"]["id"])
    assert (old["scenario_version"], old["title"], old["product_id"], old["difficulty"]) == (1, "История v1", history["a"], "easy")
    assert old["product_name"] == f"Продукт {history['a']}"
    assert (new["scenario_version"], new["title"], new["product_id"], new["difficulty"]) == (2, "История v2", history["b"], "hard")
    # Stored result untouched.
    assert old["total"] == ok(login(history["manager"]).get(f"/sessions/{history['old']['id']}/score"))["total"]


def test_lead_drilldown_uses_bound_version(history):
    manager_id = ok(login(history["manager"]).get("/auth/me"))["id"]
    rows = ok(login(history["lead"]).get(f"/dashboard/managers/{manager_id}/sessions"))["sessions"]
    assert (_row(rows, history["old"]["id"])["product_id"], _row(rows, history["old"]["id"])["difficulty"]) == (history["a"], "easy")
    assert (_row(rows, history["new"]["id"])["product_id"], _row(rows, history["new"]["id"])["difficulty"]) == (history["b"], "hard")


def test_dashboard_product_grouping_and_filter_use_bound_version(history):
    lead = login(history["lead"])
    grouped = {p["product_id"]: p for p in ok(lead.get("/dashboard/data?days=0"))["products"]}
    assert grouped[history["a"]]["sessions"] == 1 and grouped[history["b"]]["sessions"] == 1
    assert ok(lead.get(f"/dashboard/data?days=0&product_id={history['a']}"))["kpi"]["sessions_started"] == 1
    assert ok(lead.get(f"/dashboard/data?days=0&product_id={history['b']}"))["kpi"]["sessions_started"] == 1
