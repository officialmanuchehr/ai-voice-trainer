"""Phase 7 — structured content editors over the existing content API.

Round-trip: what the editor loads and sends back unchanged is stored
unchanged (scenarios: every seed shape incl. unknown profile keys and fields
with both a base value and variants; KB: every seed product incl. fact
`value`, compliance fields and extra top-level keys). Plus the two backend
correctness fixes (stale "new version from vN" can't overwrite a newer draft;
omitted KB notes are kept) and the obj_taxes P0 case (C-9) on synthetic data.
"""

import json
from pathlib import Path

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    archive_published_scenarios,
    kb_data,
    login,
    new_product,
    ok,
    publish_kb,
    say,
    scenario_data,
    server,
    start_session,
    uid,
)

SEED = Path(__file__).resolve().parent.parent / "seed"
SEED_SCENARIOS = json.loads((SEED / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
SEED_KB = json.loads((SEED / "knowledge_base.json").read_text(encoding="utf-8"))["products"]


def editor_payload(stored: dict) -> dict:
    """What the structured editor sends after loading a version and saving
    without edits: the stored object itself (it only mutates edited paths)."""
    return json.loads(json.dumps(stored))


# ------------------------------------------------------------ scenarios


@pytest.mark.parametrize("seed", SEED_SCENARIOS, ids=[s["id"] for s in SEED_SCENARIOS])
def test_scenario_round_trip_every_seed_shape(server, seed):
    trainer = login("trainer1")
    content = {k: v for k, v in seed.items() if k not in ("id", "seed_status")}
    created = ok(trainer.post("/admin/scenarios", json={"data": content}))
    loaded = ok(trainer.get(f"/admin/scenarios/{created['id']}/versions/1"))["data"]
    ok(trainer.put(f"/admin/scenarios/{created['id']}", json={"data": editor_payload(loaded), "base_version": 1}))
    again = ok(trainer.get(f"/admin/scenarios/{created['id']}/versions/1"))["data"]
    assert again == loaded
    # The stored profile is the seed profile, key for key and in order.
    assert list(again["client_profile"]) == list(seed["client_profile"])
    assert again["client_profile"] == seed["client_profile"]
    assert again["config"] == {**{"learning_goal": "", "criteria_weights": {}, "good_examples": [], "feedback_hints": []}, **seed["config"]}


def test_profile_field_with_base_value_and_variants_and_unknown_key_survive(server):
    trainer = login("trainer1")
    data = scenario_data("merchant_onboarding")
    data["client_profile"] = {
        **data["client_profile"],
        "business_type": "база",
        "variants": {**data["client_profile"].get("variants", {}), "business_type": ["вариант 1", "вариант 2"]},
        "decision_criteria": ["скорость", "цена", "надёжность"],
        "current_products": ["счёт", "карта"],
        "custom_unknown_key": {"nested": [1, 2, 3]},
    }
    sid = ok(trainer.post("/admin/scenarios", json={"data": data}))["id"]
    loaded = ok(trainer.get(f"/admin/scenarios/{sid}/versions/1"))["data"]
    ok(trainer.put(f"/admin/scenarios/{sid}", json={"data": editor_payload(loaded), "base_version": 1}))
    profile = ok(trainer.get(f"/admin/scenarios/{sid}/versions/1"))["data"]["client_profile"]
    assert profile["business_type"] == "база" and profile["variants"]["business_type"] == ["вариант 1", "вариант 2"]
    assert profile["decision_criteria"] == ["скорость", "цена", "надёжность"]
    assert profile["current_products"] == ["счёт", "карта"]
    assert profile["custom_unknown_key"] == {"nested": [1, 2, 3]}


def _published_scenario():
    trainer = login("trainer1")
    sid = ok(trainer.post("/admin/scenarios", json={"data": scenario_data("merchant_onboarding")}))["id"]
    ok(login("product1").post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}))
    ok(trainer.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}))
    return sid


def test_new_version_from_published_never_overwrites_a_newer_draft(server):
    trainer = login("trainer1")
    sid = _published_scenario()
    v1 = ok(trainer.get(f"/admin/scenarios/{sid}/versions/1"))["data"]
    first = ok(trainer.put(f"/admin/scenarios/{sid}", json={"data": {**v1, "title": "черновик A"}, "base_version": 1}))
    assert first["version"] == 2
    # A second editor still looking at v1 tries "new version based on v1": refused, draft v2 kept.
    stale = trainer.put(f"/admin/scenarios/{sid}", json={"data": {**v1, "title": "черновик B"}, "base_version": 1})
    assert stale.status_code == 409 and "v2" in stale.json()["detail"]
    assert ok(trainer.get(f"/admin/scenarios/{sid}/versions/2"))["data"]["title"] == "черновик A"
    # Editing the draft itself works; v1 (published) never changes.
    ok(trainer.put(f"/admin/scenarios/{sid}", json={"data": {**v1, "title": "черновик A2"}, "base_version": 2}))
    assert ok(trainer.get(f"/admin/scenarios/{sid}/versions/2"))["data"]["title"] == "черновик A2"
    assert ok(trainer.get(f"/admin/scenarios/{sid}/versions/1"))["data"] == v1
    assert ok(trainer.get(f"/admin/scenarios/{sid}/versions/1"))["status"] == "published"


def test_put_without_base_version_keeps_legacy_behaviour(server):
    trainer = login("trainer1")
    sid = _published_scenario()
    v1 = ok(trainer.get(f"/admin/scenarios/{sid}/versions/1"))["data"]
    assert ok(trainer.put(f"/admin/scenarios/{sid}", json={"data": v1}))["version"] == 2
    assert ok(trainer.put(f"/admin/scenarios/{sid}", json={"data": v1}))["version"] == 2


def test_manager_catalogue_still_hides_hidden_fields_of_structured_content(server):
    trainer = login("trainer1")
    data = scenario_data("merchant_onboarding")
    data["client_profile"] = {**data["client_profile"], "pain": "HIDDEN_PAIN_P7", "hidden_need": "HIDDEN_NEED_P7", "decision_criteria": ["HIDDEN_CRIT_P7"]}
    data["config"] = {**data.get("config", {}), "good_examples": ["HIDDEN_EXAMPLE_P7"], "feedback_hints": ["HIDDEN_HINT_P7"]}
    sid = ok(trainer.post("/admin/scenarios", json={"data": data}))["id"]
    ok(login("product1").post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}))
    ok(trainer.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}))
    manager = login("manager1")
    text = manager.get("/scenarios").text + json.dumps(start_session(manager, sid), ensure_ascii=False)
    for secret in ("HIDDEN_PAIN_P7", "HIDDEN_NEED_P7", "HIDDEN_CRIT_P7", "HIDDEN_EXAMPLE_P7", "HIDDEN_HINT_P7"):
        assert secret not in text, secret


def test_meta_exposes_profile_catalogue_from_backend_constants(server):
    from app.client_generator import BRIEFING_FIELDS
    from app.prompts import PROFILE_LIST_FIELDS, profile_field_labels

    fields = ok(login("trainer1").get("/admin/meta"))["profile_fields"]
    assert [f["id"] for f in fields] == list(profile_field_labels())
    assert {f["id"] for f in fields if f["briefing"]} == set(BRIEFING_FIELDS)
    assert {f["id"] for f in fields if f["list"]} == PROFILE_LIST_FIELDS
    assert ok(login("manager1").get("/scenarios")) is not None
    assert login("manager1").get("/admin/meta").status_code == 403


# ------------------------------------------------------------ knowledge base


@pytest.mark.parametrize("seed", SEED_KB, ids=[p["id"] for p in SEED_KB])
def test_kb_round_trip_every_seed_product(server, seed):
    """A new draft copied from the seed KB, saved unchanged, keeps every field:
    fact type/value (numbers stay numbers), compliance fields, needs_review,
    draft_note, exercise_type/rubric_id/goal."""
    product = login("product1")
    version = uid("rt")
    ok(product.post(f"/admin/kb/{seed['id']}/versions", json={"version": version, "base_version": "1.0.0", "notes": "заметка"}))
    loaded = ok(product.get(f"/admin/kb/{seed['id']}/versions/{version}"))
    ok(product.put(f"/admin/kb/{seed['id']}/versions/{version}", json={"data": editor_payload(loaded["data"]), "notes": loaded["notes"]}))
    again = ok(product.get(f"/admin/kb/{seed['id']}/versions/{version}"))
    assert again["data"] == loaded["data"] and again["notes"] == "заметка"
    expected = {k: v for k, v in seed.items() if k != "seed_status"}
    assert again["data"] == expected
    for fact in again["data"]["approved_facts"]:
        if "value" in fact:
            assert isinstance(fact["value"]["limit"], int) and isinstance(fact["value"]["commission_pct"], int)


def test_kb_notes_kept_when_omitted_and_changed_when_sent(server):
    pid = new_product("p7n", publish=False)
    product = login("product1")
    ok(product.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid), "notes": "первая"}))
    ok(product.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid)}))
    assert ok(product.get(f"/admin/kb/{pid}/versions/1.0.0"))["notes"] == "первая"
    ok(product.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid), "notes": ""}))
    assert ok(product.get(f"/admin/kb/{pid}/versions/1.0.0"))["notes"] == ""


def test_kb_list_reports_blockers_per_version(server):
    listing = {p["product_id"]: p for p in ok(login("product1").get("/admin/kb"))}
    rko = next(v for v in listing["rko"]["versions"] if v["version"] == "1.0.0")
    assert rko["review_blockers"] == 6  # draft_note + 5 facts flagged in the seed
    merchant = next(v for v in listing["merchant_onboarding"]["versions"] if v["version"] == "1.0.0")
    assert merchant["review_blockers"] == 0


# ------------------------------------------------------------ the obj_taxes P0 case (C-9)


def test_real_merchant_kb_finding_is_as_audited(server):
    """Documents C-9: published merchant_onboarding 1.0.0 carries obj_taxes
    with a 'confirm before publication' compliance note but no needs_review,
    so the guard sees it as clean. Read-only — the version is not modified."""
    v = ok(login("compliance1").get("/admin/kb/merchant_onboarding/versions/1.0.0"))
    taxes = next(o for o in v["data"]["objections"] if o["id"] == "obj_taxes")
    assert v["status"] == "published"
    assert taxes["compliance_owned"] is True and "До публикации" in taxes["compliance_note"]
    assert not taxes.get("needs_review")


def test_corrective_draft_flow_for_unresolved_compliance_content(server):
    """Synthetic replica of C-9: a published KB with a compliance-sensitive
    objection → sessions bound to it → corrective draft with needs_review on
    that entry → blocked → explicit edit clears it → normal lifecycle."""
    sensitive = {"id": "obj_sensitive", "trigger": "Тестовое возражение", "approved_response": "SYNTHETIC_UNCONFIRMED_STATEMENT",
                 "compliance_owned": True, "compliance_note": "Тест: до публикации подтвердить комплаенсом."}
    pid = uid("p7tax")
    publish_kb(pid, "1.0.0", kb_data(pid, objections=[sensitive]))
    published = ok(login("product1").get(f"/admin/kb/{pid}/versions/1.0.0"))

    # A session bound to 1.0.0.
    trainer = login("trainer1")
    sid = ok(trainer.post("/admin/scenarios", json={"data": scenario_data(pid)}))["id"]
    ok(login("product1").post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}))
    ok(trainer.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}))
    session = start_session(login("manager1"), sid)
    assert session["kb_version"] == "1.0.0"

    # Corrective draft: copy of 1.0.0 with the unresolved entry flagged.
    product, compliance = login("product1"), login("compliance1")
    ok(product.post(f"/admin/kb/{pid}/versions", json={"version": "1.1.0", "base_version": "1.0.0"}))
    draft = ok(product.get(f"/admin/kb/{pid}/versions/1.1.0"))["data"]
    next(o for o in draft["objections"] if o["id"] == "obj_sensitive")["needs_review"] = True
    ok(product.put(f"/admin/kb/{pid}/versions/1.1.0", json={"data": draft}))
    assert ok(product.get(f"/admin/kb/{pid}/versions/1.0.0")) == published  # 1.0.0 untouched

    # Blocked while flagged — approve and publish both refused with the exact entry.
    for client, target in ((compliance, "approved"), (product, "published")):
        response = client.post(f"/admin/kb/{pid}/versions/1.1.0/status", json={"status": target})
        assert response.status_code in (400, 409), target
    refused = compliance.post(f"/admin/kb/{pid}/versions/1.1.0/status", json={"status": "approved"})
    assert refused.status_code == 409 and refused.json()["code"] == "kb_unreviewed"
    assert {"section": "objections", "id": "obj_sensitive"} in refused.json()["unreviewed"]

    # Saving other edits never clears the flag.
    draft["segment"] = "другой тестовый сегмент"
    ok(product.put(f"/admin/kb/{pid}/versions/1.1.0", json={"data": draft}))
    assert next(o for o in ok(product.get(f"/admin/kb/{pid}/versions/1.1.0"))["data"]["objections"] if o["id"] == "obj_sensitive")["needs_review"] is True

    # Explicit resolution by an authorized editor (synthetic wording), then the normal lifecycle.
    entry = next(o for o in draft["objections"] if o["id"] == "obj_sensitive")
    entry["approved_response"] = "SYNTHETIC_CONFIRMED_STATEMENT"
    del entry["needs_review"]
    ok(compliance.put(f"/admin/kb/{pid}/versions/1.1.0", json={"data": draft}))
    ok(compliance.post(f"/admin/kb/{pid}/versions/1.1.0/status", json={"status": "approved"}))
    ok(product.post(f"/admin/kb/{pid}/versions/1.1.0/status", json={"status": "published"}))
    assert ok(product.get(f"/admin/kb/{pid}/versions/1.0.0"))["status"] == "archived"
    assert ok(product.get(f"/admin/kb/{pid}/versions/1.0.0"))["data"] == published["data"]  # content never rewritten

    # The old session stays bound to 1.0.0; a new session binds to 1.1.0.
    assert ok(login("manager1").get(f"/sessions/{session['id']}/score")) is not None
    say(login("manager1"), session["id"])
    assert start_session(login("manager1"), sid)["kb_version"] == "1.1.0"
    history = ok(login("manager1").get("/me/sessions"))
    assert next(r for r in history if r["id"] == session["id"])["kb_version"] == "1.0.0"


# ------------------------------------------------------------ roles (server-side)


@pytest.mark.parametrize("username,can_edit_scenario,can_edit_kb", [
    ("trainer1", True, False), ("product1", False, True), ("compliance1", False, True), ("admin", True, True), ("manager1", False, False), ("lead1", False, False),
])
def test_edit_permissions_enforced_server_side(server, username, can_edit_scenario, can_edit_kb):
    client = login(username)
    scenario = client.post("/admin/scenarios", json={"data": scenario_data("merchant_onboarding")})
    assert (scenario.status_code == 200) == can_edit_scenario, scenario.text
    pid = new_product("p7r", publish=False)
    kb = client.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid)})
    assert (kb.status_code == 200) == can_edit_kb, kb.text


@pytest.mark.parametrize("username,approve,publish", [
    ("trainer1", 403, 200), ("product1", 200, 403), ("compliance1", 200, 403), ("admin", 200, 200),
])
def test_scenario_transition_roles_unchanged(server, username, approve, publish):
    trainer = login("trainer1")
    sid = ok(trainer.post("/admin/scenarios", json={"data": scenario_data("merchant_onboarding")}))["id"]
    assert login(username).post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}).status_code == approve
    if approve != 200:
        ok(login("product1").post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}))
    assert login(username).post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}).status_code == publish


@pytest.mark.parametrize("username,approve,publish", [
    ("product1", 403, 200), ("compliance1", 200, 403), ("admin", 200, 200), ("trainer1", 403, 403),
])
def test_kb_transition_roles_unchanged(server, username, approve, publish):
    pid = new_product("p7t", publish=False)
    assert login(username).post(f"/admin/kb/{pid}/versions/1.0.0/status", json={"status": "approved"}).status_code == approve
    if approve != 200:
        ok(login("compliance1").post(f"/admin/kb/{pid}/versions/1.0.0/status", json={"status": "approved"}))
    assert login(username).post(f"/admin/kb/{pid}/versions/1.0.0/status", json={"status": "published"}).status_code == publish


def test_published_kb_cannot_be_edited_in_place(server):
    pid = new_product("p7i")
    response = login("product1").put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid, segment="изменено")})
    assert response.status_code == 409
    assert ok(login("product1").get(f"/admin/kb/{pid}/versions/1.0.0"))["data"]["segment"] == "тестовый сегмент"


def test_scenario_publish_still_requires_clean_published_kb(server):
    pid = uid("p7k")
    publish_kb(pid, "1.0.0", kb_data(pid))
    product = login("product1")
    ok(product.post(f"/admin/kb/{pid}/versions", json={"version": "1.1.0", "base_version": "1.0.0"}))
    trainer = login("trainer1")
    sid = ok(trainer.post("/admin/scenarios", json={"data": scenario_data(pid)}))["id"]
    ok(product.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}))
    ok(product.post(f"/admin/kb/{pid}/versions/1.0.0/status", json={"status": "archived"}))
    assert trainer.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}).status_code == 409
