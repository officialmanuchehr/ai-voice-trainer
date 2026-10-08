"""Phase 2 — hidden scenario information: hidden from the manager, available
to the AI client (and, for coaching material, to the scorer).

Every hidden field gets a unique sentinel VALUE; the tests search the raw
serialized responses for those values, not just for field names.
"""

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    archive_published_scenarios,
    Capture,
    finish_and_score,
    login,
    new_product,
    ok,
    published_scenario,
    server,
    start_session,
)

# Hidden client-profile fields: every key app/prompts.py feeds the AI client
# that is not one of the manager-visible BRIEFING_FIELDS.
HIDDEN = {
    "turnover": "SECRET_TURNOVER_7101",
    "current_products": "SECRET_CURRENT_PRODUCTS_7102",
    "business_context": "SECRET_BUSINESS_CONTEXT_7103",
    "explicit_needs": "SECRET_EXPLICIT_NEEDS_7104",
    "pain": "SECRET_PAIN_7105",
    "hidden_need": "SECRET_HIDDEN_NEED_7106",
    "financial_literacy": "SECRET_FIN_LITERACY_7107",
    "style": "SECRET_STYLE_7108",
    "emotion": "SECRET_EMOTION_7109",
    "decision_criteria": "SECRET_DECISION_CRITERIA_7110",
    "attitude_to_bank": "SECRET_ATTITUDE_7111",
    "trust_level": "SECRET_TRUST_7112",
}
HIDDEN_LIST = {"objections": ["SECRET_OBJECTION_A_7113", "SECRET_OBJECTION_B_7114"]}
# Hidden fields that vary per session: whichever option is drawn must stay hidden.
HIDDEN_VARIANTS = {"urgency": ["SECRET_URGENCY_V1_7115", "SECRET_URGENCY_V2_7116"]}
# Coaching material: guides feedback after the session, never shown while training.
COACHING = {"good_examples": ["SECRET_GOOD_EXAMPLE_7117"], "feedback_hints": ["SECRET_FEEDBACK_HINT_7118"]}

VISIBLE = {
    "persona_name": "Видимая Персона",
    "business_type": "видимый тип бизнеса",
    "company_size": "видимый размер",
    "employees": "видимые 12 сотрудников",
    "owner": "видимая роль",
    "current_bank": "видимый банк",
    "current_situation": "видимая ситуация",
}
VISIBLE_VARIANTS = {"industry": ["видимая отрасль А", "видимая отрасль Б"]}

ALL_SECRETS = (
    list(HIDDEN.values())
    + HIDDEN_LIST["objections"]
    + HIDDEN_VARIANTS["urgency"]
    + COACHING["good_examples"]
    + COACHING["feedback_hints"]
)
# What the AI client must receive (coaching material goes to the scorer instead).
CLIENT_SECRETS = list(HIDDEN.values()) + HIDDEN_LIST["objections"]


@pytest.fixture(scope="module")
def secret_scenario(server):
    product_id = new_product("p2hidden")
    profile = {**VISIBLE, **HIDDEN, **HIDDEN_LIST, "variants": {**HIDDEN_VARIANTS, **VISIBLE_VARIANTS}}
    config = {"learning_goal": "видимая учебная цель", "criteria_weights": {}, **COACHING}
    return published_scenario(product_id, client_profile=profile, config=config, goal="видимая цель разговора")


def assert_no_secrets(text: str, where: str):
    leaked = [s for s in ALL_SECRETS if s in text]
    assert not leaked, f"hidden values leaked in {where}: {leaked}"


@pytest.mark.parametrize("username", ["manager1", "lead1"])
def test_catalogue_shows_briefing_but_no_hidden_values(server, secret_scenario, username):
    response = login(username).get("/scenarios")
    assert_no_secrets(response.text, "GET /scenarios")
    item = next(s for s in response.json() if s["id"] == secret_scenario)
    shown = {b["label"]: b["value"] for b in item["briefing"]}
    assert shown["Клиент"] == "Видимая Персона"
    assert shown["Отрасль"] == "варьируется"  # visible variant field, not yet drawn


def test_every_manager_endpoint_during_training_is_clean(server, secret_scenario, monkeypatch):
    capture = Capture(monkeypatch)
    manager = login("manager1")

    created = manager.post("/sessions", json={"scenario_id": secret_scenario})
    assert_no_secrets(created.text, "POST /sessions")
    session = created.json()
    session_id = session["id"]
    shown = {b["label"]: b["value"] for b in session["briefing"]}
    assert shown["Отрасль"] in VISIBLE_VARIANTS["industry"]  # visible variant drawn and shown
    assert shown["Текущий банк"] == "видимый банк"

    checks = {
        "POST /turns": manager.post(f"/sessions/{session_id}/turns", json={"text": "Какие у вас сложности?"}),
        "POST /voice-turn": manager.post(
            f"/sessions/{session_id}/voice-turn", files={"audio": ("turn.webm", b"\x1a\x45\xdf\xa3 fake", "audio/webm")}
        ),
        "GET /transcript": manager.get(f"/sessions/{session_id}/transcript"),
        "GET /turns/2/audio": manager.get(f"/sessions/{session_id}/turns/2/audio"),
        "GET /score (active)": manager.get(f"/sessions/{session_id}/score"),
        "GET /me/sessions": manager.get("/me/sessions"),
        "GET /scenarios": manager.get("/scenarios"),
        "GET /auth/me": manager.get("/auth/me"),
        "GET /products": manager.get("/products"),
        "GET /rubric": manager.get("/rubric"),
    }
    for where, response in checks.items():
        assert response.status_code == 200, (where, response.status_code, response.text)
        assert_no_secrets(response.text if "audio" not in where else response.content.decode("latin-1"), where)

    ok(manager.post(f"/sessions/{session_id}/finish"))
    assert_no_secrets(manager.get(f"/sessions/{session_id}/score").text, "GET /score (scoring)")

    # The AI client received every hidden client field on every turn.
    assert len(capture.prompts) == 2
    for prompt in capture.prompts:
        missing = [s for s in CLIENT_SECRETS if s not in prompt]
        assert not missing, f"AI client prompt lacks hidden context: {missing}"
        assert sum(v in prompt for v in HIDDEN_VARIANTS["urgency"]) == 1  # exactly the drawn variant


def test_hidden_values_never_reach_the_manager_as_field_names_either(server, secret_scenario):
    session = ok(login("manager1").post("/sessions", json={"scenario_id": secret_scenario}))
    labels = {b["label"] for b in session["briefing"]}
    assert labels <= {"Клиент", "Тип бизнеса", "Отрасль", "Размер компании", "Сотрудников", "Роль собеседника", "Текущий банк", "Ситуация"}
    assert not {"client_profile", "pain", "hidden_need", "objections", "decision_criteria", "config"} & set(session)


def test_coaching_material_reaches_the_scorer(server, secret_scenario, monkeypatch):
    capture = Capture(monkeypatch)
    manager = login("manager1")
    session_id = start_session(manager, secret_scenario)["id"]
    ok(manager.post(f"/sessions/{session_id}/turns", json={"text": "Добрый день"}))
    finish_and_score(manager, session_id)
    context = capture.score_rubrics[-1]["scenario_context"]
    assert context["good_examples"] == COACHING["good_examples"]
    assert context["feedback_hints"] == COACHING["feedback_hints"]


def test_content_roles_can_still_author_hidden_fields(server, secret_scenario):
    """The protection is about managers — the training team must see what it wrote."""
    data = ok(login("trainer1").get(f"/admin/scenarios/{secret_scenario}/versions/1"))["data"]
    assert data["client_profile"]["hidden_need"] == HIDDEN["hidden_need"]
    assert login("manager1").get(f"/admin/scenarios/{secret_scenario}/versions/1").status_code == 403

