"""Phase 2 — a running session never switches scenario or KB version.

Each test publishes v1, starts a session, publishes v2 while the session is
running, then checks what the AI client, the claim checker, the scorer and the
stored result actually used — plus that a new session picks up v2.
"""

from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    approve_and_publish_scenario,
    archive_published_scenarios,
    CRITERIA,
    Capture,
    finish_and_score,
    kb_data,
    login,
    new_product,
    ok,
    publish_kb,
    published_scenario,
    say,
    scenario_data,
    server,
    start_session,
)

# One full-marks criterion each, so the total shows which weights were applied.
V1_WEIGHTS = {c: (100 if c == "contact" else 0) for c in CRITERIA}
V2_WEIGHTS = {c: (100 if c == "next_step" else 0) for c in CRITERIA}
BREAKDOWN = [{"criterion_id": c, "score": 10 if c == "contact" else 0, "max": 10} for c in CRITERIA]


def _scenario_versions(scenario_id):
    item = next(s for s in ok(login("trainer1").get("/admin/scenarios")) if s["id"] == scenario_id)
    return {v["version"]: v["status"] for v in item["versions"]}, item["published_version"]


def test_running_session_stays_on_its_scenario_version(server, monkeypatch):
    capture = Capture(monkeypatch, breakdown=BREAKDOWN)
    product_id = new_product("p2scn")
    base = scenario_data(product_id)
    v1 = {
        **base,
        "difficulty": "easy",
        "goal": "V1_GOAL_SENTINEL",
        "client_profile": {**base["client_profile"], "pain": "V1_PAIN_SENTINEL"},
        "config": {**base["config"], "criteria_weights": V1_WEIGHTS, "feedback_hints": ["V1_HINT_SENTINEL"]},
    }
    scenario_id = published_scenario(product_id, **{k: v for k, v in v1.items() if k != "product_id"})
    manager = login("manager1")

    old = start_session(manager, scenario_id)
    assert old["scenario_version"] == 1
    say(manager, old["id"])

    # v2 while the session is running: editing a published scenario creates a new draft version.
    v2 = {
        **v1,
        "difficulty": "hard",
        "goal": "V2_GOAL_SENTINEL",
        "client_profile": {**base["client_profile"], "pain": "V2_PAIN_SENTINEL"},
        "config": {**v1["config"], "criteria_weights": V2_WEIGHTS, "feedback_hints": ["V2_HINT_SENTINEL"]},
    }
    assert ok(login("trainer1").put(f"/admin/scenarios/{scenario_id}", json={"data": v2}))["version"] == 2
    approve_and_publish_scenario(scenario_id, 2)
    assert _scenario_versions(scenario_id) == ({1: "archived", 2: "published"}, 2)

    # The running session keeps simulating v1.
    say(manager, old["id"], "Продолжим?")
    for prompt in capture.prompts[:2]:
        assert "V1_PAIN_SENTINEL" in prompt and "V2_PAIN_SENTINEL" not in prompt
        assert "ЛЁГКИЙ" in prompt and "СЛОЖНЫЙ" not in prompt

    # ...and is scored against v1's goal, hints and weights.
    result = finish_and_score(manager, old["id"])
    context = capture.score_rubrics[-1]["scenario_context"]
    assert (context["goal"], context["feedback_hints"], context["difficulty"]) == ("V1_GOAL_SENTINEL", ["V1_HINT_SENTINEL"], "easy")
    assert result["scenario_version"] == 1
    assert result["total"] == 100  # contact-only weights of v1
    assert {b["criterion_id"]: b["weight"] for b in result["breakdown"]}["contact"] == 100

    # A new session uses v2 everywhere.
    new = start_session(manager, scenario_id)
    assert new["scenario_version"] == 2 and new["goal"] == "V2_GOAL_SENTINEL"
    say(manager, new["id"])
    assert "V2_PAIN_SENTINEL" in capture.prompts[-1] and "СЛОЖНЫЙ" in capture.prompts[-1]
    new_result = finish_and_score(manager, new["id"])
    assert new_result["scenario_version"] == 2
    assert new_result["total"] == 0  # next_step-only weights of v2, next_step scored 0
    assert capture.score_rubrics[-1]["scenario_context"]["goal"] == "V2_GOAL_SENTINEL"

    # The old result is unchanged when read again after v2 went live.
    again = ok(manager.get(f"/sessions/{old['id']}/score"))
    assert (again["scenario_version"], again["total"]) == (1, 100)


def test_running_session_stays_on_its_kb_version(server, monkeypatch):
    capture = Capture(monkeypatch)
    v1_kb = {
        "approved_facts": [{"id": "fact_v1", "type": "condition", "text": "KB_V1_FACT_SENTINEL"}],
        "objections": [{"id": "obj_v1", "trigger": "KB_V1_OBJECTION_SENTINEL", "approved_response": "ответ v1"}],
        "forbidden": ["KB_V1_FORBIDDEN_SENTINEL"],
    }
    product_id = new_product("p2kb", **v1_kb)
    scenario_id = published_scenario(product_id)
    manager = login("manager1")

    old = start_session(manager, scenario_id)
    assert old["kb_version"] == "1.0.0"
    say(manager, old["id"])

    v2_kb = kb_data(
        product_id,
        approved_facts=[{"id": "fact_v2", "type": "condition", "text": "KB_V2_FACT_SENTINEL"}],
        objections=[{"id": "obj_v2", "trigger": "KB_V2_OBJECTION_SENTINEL", "approved_response": "ответ v2"}],
        forbidden=["KB_V2_FORBIDDEN_SENTINEL"],
    )
    publish_kb(product_id, "2.0.0", v2_kb)
    kb_versions = {v["version"]: v["status"] for p in ok(login("product1").get("/admin/kb")) if p["product_id"] == product_id for v in p["versions"]}
    assert kb_versions == {"1.0.0": "archived", "2.0.0": "published"}

    # The running session's AI client still knows only v1 facts.
    say(manager, old["id"], "Какие условия?")
    for prompt in capture.prompts[:2]:
        assert "KB_V1_FACT_SENTINEL" in prompt and "KB_V1_OBJECTION_SENTINEL" in prompt
        assert "KB_V2" not in prompt

    # Claim checking and scoring use the v1 snapshot.
    result = finish_and_score(manager, old["id"])
    checked_kb = capture.claim_kbs[-1]
    assert [f["text"] for f in checked_kb["approved_facts"]] == ["KB_V1_FACT_SENTINEL"]
    assert checked_kb["forbidden"] == ["KB_V1_FORBIDDEN_SENTINEL"]
    assert result["kb_version"] == "1.0.0"
    assert ok(manager.get(f"/sessions/{old['id']}/transcript"))["kb_version"] == "1.0.0"

    # A new session binds v2.
    new = start_session(manager, scenario_id)
    assert new["kb_version"] == "2.0.0"
    say(manager, new["id"])
    assert "KB_V2_FACT_SENTINEL" in capture.prompts[-1] and "KB_V1" not in capture.prompts[-1]
    finish_and_score(manager, new["id"])
    assert [f["text"] for f in capture.claim_kbs[-1]["approved_facts"]] == ["KB_V2_FACT_SENTINEL"]

    assert ok(manager.get(f"/sessions/{old['id']}/score"))["kb_version"] == "1.0.0"


def test_session_binds_only_the_published_kb(server, monkeypatch):
    """Newer approved or draft KB versions never reach a session."""
    capture = Capture(monkeypatch)
    product_id = new_product("p2pub", approved_facts=[{"id": "f", "text": "PUBLISHED_FACT_SENTINEL"}])
    scenario_id = published_scenario(product_id)
    ok(login("product1").post(f"/admin/kb/{product_id}/versions", json={"version": "2.0.0", "data": kb_data(product_id, approved_facts=[{"id": "f", "text": "APPROVED_FACT_SENTINEL"}])}))
    ok(login("compliance1").post(f"/admin/kb/{product_id}/versions/2.0.0/status", json={"status": "approved"}))
    ok(login("product1").post(f"/admin/kb/{product_id}/versions", json={"version": "3.0.0", "data": kb_data(product_id, approved_facts=[{"id": "f", "text": "DRAFT_FACT_SENTINEL"}])}))

    manager = login("manager1")
    session = start_session(manager, scenario_id)
    assert session["kb_version"] == "1.0.0"
    say(manager, session["id"])
    assert "PUBLISHED_FACT_SENTINEL" in capture.prompts[-1]
    assert "APPROVED_FACT_SENTINEL" not in capture.prompts[-1] and "DRAFT_FACT_SENTINEL" not in capture.prompts[-1]


def test_archiving_the_kb_hides_the_scenario_but_running_sessions_continue(server, monkeypatch):
    capture = Capture(monkeypatch)
    product_id = new_product("p2arch", approved_facts=[{"id": "f", "text": "ARCHIVED_KB_FACT_SENTINEL"}])
    scenario_id = published_scenario(product_id)
    manager = login("manager1")
    running = start_session(manager, scenario_id)

    ok(login("product1").post(f"/admin/kb/{product_id}/versions/1.0.0/status", json={"status": "archived"}))

    assert scenario_id not in [s["id"] for s in ok(manager.get("/scenarios"))]
    assert manager.post("/sessions", json={"scenario_id": scenario_id}).status_code == 409
    say(manager, running["id"])  # bound snapshot still serves the running session
    assert "ARCHIVED_KB_FACT_SENTINEL" in capture.prompts[-1]
    assert finish_and_score(manager, running["id"])["kb_version"] == "1.0.0"

