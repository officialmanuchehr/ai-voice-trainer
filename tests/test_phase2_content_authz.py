"""Phase 2 — role × content-route authorization at the HTTP level.

Documents the CURRENT role model (app/security.py), no four-eyes rule:
  read content           training, product, compliance, admin
  scenario create/edit   training, admin
  scenario approve       product, compliance, admin
  scenario publish/arch. training, admin
  scenario back to draft training, product, compliance, admin
  KB create/edit         product, compliance, admin
  KB approve             compliance, admin
  KB publish/archive     product, admin
  KB back to draft       product, compliance, admin
Manager and sales lead are refused every content route. (The policy function
itself is proven equivalent to the old rules exhaustively in test_phase1.py;
this file proves the endpoints are wired to it and that refusals change nothing.)
"""

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    archive_published_scenarios,
    ALL_ROLES_USERS,
    create_scenario,
    kb_data,
    login,
    new_product,
    ok,
    published_scenario,
    scenario_data,
    server,
    uid,
)

ROLES = list(ALL_ROLES_USERS)
VIEW = {"training", "product", "compliance", "admin"}


def allowed(roles):
    return [(role, role in roles) for role in ROLES]


# ------------------------------------------------------------------ reads

READS = [
    "/admin/meta",
    "/admin/scenarios",
    "/admin/scenarios/scn_merchant_onboarding_medium_01/versions/1",
    "/admin/kb",
    "/admin/kb/merchant_onboarding/versions/1.0.0",
    "/kb/merchant_onboarding",
]


@pytest.mark.parametrize("path", READS)
@pytest.mark.parametrize("role,permitted", allowed(VIEW))
def test_content_reads(server, path, role, permitted):
    response = login(ALL_ROLES_USERS[role]).get(path)
    assert response.status_code == (200 if permitted else 403), response.text


# ------------------------------------------------------- scenario writes


def _scenario_versions(scenario_id):
    item = next(s for s in ok(login("admin").get("/admin/scenarios")) if s["id"] == scenario_id)
    return [(v["version"], v["status"]) for v in item["versions"]]


@pytest.mark.parametrize("role,permitted", allowed({"training", "admin"}))
def test_scenario_create(server, role, permitted):
    title = uid("authz-create")
    data = scenario_data("merchant_onboarding", title=title)
    response = login(ALL_ROLES_USERS[role]).post("/admin/scenarios", json={"data": data})
    assert response.status_code == (200 if permitted else 403), response.text
    titles = [s["title"] for s in ok(login("admin").get("/admin/scenarios"))]
    assert (title in titles) == permitted


@pytest.mark.parametrize("role,permitted", allowed({"training", "admin"}))
def test_scenario_edit_creates_or_updates_draft(server, role, permitted):
    product_id = new_product("p2az")
    scenario_id = published_scenario(product_id)
    before = _scenario_versions(scenario_id)
    data = scenario_data(product_id, title=uid("edited"))
    response = login(ALL_ROLES_USERS[role]).put(f"/admin/scenarios/{scenario_id}", json={"data": data})
    assert response.status_code == (200 if permitted else 403), response.text
    after = _scenario_versions(scenario_id)
    # Editing a published scenario never touches v1: it adds a draft v2.
    assert after == (before + [(2, "draft")] if permitted else before)


SCENARIO_TRANSITIONS = {
    # target: (status the version must be in first, roles allowed)
    "approved": ("draft", {"product", "compliance", "admin"}),
    "published": ("approved", {"training", "admin"}),
    "archived": ("published", {"training", "admin"}),
    "draft": ("approved", {"training", "product", "compliance", "admin"}),
}


def _scenario_in(status, product_id):
    scenario_id = create_scenario(scenario_data(product_id))
    path = f"/admin/scenarios/{scenario_id}/versions/1/status"
    if status in ("approved", "published"):
        ok(login("product1").post(path, json={"status": "approved"}))
    if status == "published":
        ok(login("trainer1").post(path, json={"status": "published"}))
    return scenario_id


@pytest.fixture(scope="module")
def authz_product(server):
    return new_product("p2azkb")


@pytest.mark.parametrize("target", SCENARIO_TRANSITIONS)
@pytest.mark.parametrize("role", ROLES)
def test_scenario_status_transitions(authz_product, target, role):
    start, roles = SCENARIO_TRANSITIONS[target]
    scenario_id = _scenario_in(start, authz_product)
    response = login(ALL_ROLES_USERS[role]).post(f"/admin/scenarios/{scenario_id}/versions/1/status", json={"status": target})
    permitted = role in roles
    assert response.status_code == (200 if permitted else 403), (role, target, response.text)
    assert _scenario_versions(scenario_id) == [(1, target if permitted else start)]


# ------------------------------------------------------------- KB writes


@pytest.mark.parametrize("role,permitted", allowed({"product", "compliance", "admin"}))
def test_kb_create_version(server, role, permitted):
    product_id = uid("p2azc")
    response = login(ALL_ROLES_USERS[role]).post(f"/admin/kb/{product_id}/versions", json={"version": "1.0.0", "data": kb_data(product_id)})
    assert response.status_code == (200 if permitted else 403), response.text
    exists = any(p["product_id"] == product_id for p in ok(login("admin").get("/admin/kb")))
    assert exists == permitted


@pytest.mark.parametrize("role,permitted", allowed({"product", "compliance", "admin"}))
def test_kb_edit_draft(server, role, permitted):
    product_id = new_product("p2aze", publish=False)
    edited = kb_data(product_id, approved_facts=[{"id": "f", "text": "EDITED_FACT"}])
    response = login(ALL_ROLES_USERS[role]).put(f"/admin/kb/{product_id}/versions/1.0.0", json={"data": edited})
    assert response.status_code == (200 if permitted else 403), response.text
    facts = ok(login("admin").get(f"/admin/kb/{product_id}/versions/1.0.0"))["data"]["approved_facts"]
    assert (facts[0]["text"] == "EDITED_FACT") == permitted


KB_TRANSITIONS = {
    "approved": ("draft", {"compliance", "admin"}),
    "published": ("approved", {"product", "admin"}),
    "archived": ("published", {"product", "admin"}),
    "draft": ("approved", {"product", "compliance", "admin"}),
}


def _kb_in(status):
    product_id = new_product("p2azs", publish=False)
    path = f"/admin/kb/{product_id}/versions/1.0.0/status"
    if status in ("approved", "published"):
        ok(login("compliance1").post(path, json={"status": "approved"}))
    if status == "published":
        ok(login("product1").post(path, json={"status": "published"}))
    return product_id


@pytest.mark.parametrize("target", KB_TRANSITIONS)
@pytest.mark.parametrize("role", ROLES)
def test_kb_status_transitions(server, target, role):
    start, roles = KB_TRANSITIONS[target]
    product_id = _kb_in(start)
    response = login(ALL_ROLES_USERS[role]).post(f"/admin/kb/{product_id}/versions/1.0.0/status", json={"status": target})
    permitted = role in roles
    assert response.status_code == (200 if permitted else 403), (role, target, response.text)
    status = ok(login("admin").get(f"/admin/kb/{product_id}/versions/1.0.0"))["status"]
    assert status == (target if permitted else start)


def test_no_four_eyes_rule_at_the_endpoint(server):
    """B-1 pending: the same admin may create, approve and publish alone (documented, not endorsed)."""
    admin = login("admin")
    product_id = uid("p2solo")
    ok(admin.post(f"/admin/kb/{product_id}/versions", json={"version": "1.0.0", "data": kb_data(product_id)}))
    ok(admin.post(f"/admin/kb/{product_id}/versions/1.0.0/status", json={"status": "approved"}))
    ok(admin.post(f"/admin/kb/{product_id}/versions/1.0.0/status", json={"status": "published"}))
