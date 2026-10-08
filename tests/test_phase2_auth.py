"""Phase 2 — authentication edge cases not covered elsewhere: expired login
cookies, and cookies of users deactivated after they logged in."""

import time

from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    PASSWORD,
    archive_published_scenarios,
    login,
    ok,
    server,
    uid,
)

from app.main import app
from app.security import COOKIE_NAME, _sign
from fastapi.testclient import TestClient


def _user_id(username):
    return next(u["id"] for u in ok(login("admin").get("/admin/users")) if u["username"] == username)


def _client_with_token(user_id, expires):
    payload = f"{user_id}.{expires}"
    return TestClient(app, cookies={COOKIE_NAME: f"{payload}.{_sign(payload)}"})


def test_validly_signed_but_expired_cookie_is_rejected(server):
    user_id = _user_id("manager1")
    assert _client_with_token(user_id, int(time.time()) + 600).get("/auth/me").status_code == 200
    assert _client_with_token(user_id, int(time.time()) - 1).get("/auth/me").status_code == 401


def test_cookie_of_deactivated_user_stops_working_immediately(server):
    username = uid("leaver")
    admin = login("admin")
    created = ok(admin.post("/admin/users", json={"username": username, "full_name": "Уходящий", "role": "manager", "password": PASSWORD}))
    session = login(username)
    assert session.get("/scenarios").status_code == 200

    edit = {"full_name": "Уходящий", "role": "manager", "team_id": None, "is_active": False}
    ok(admin.put(f"/admin/users/{created['id']}", json=edit))
    assert session.get("/scenarios").status_code == 401
    assert session.post("/sessions", json={"scenario_id": "scn_merchant_onboarding_medium_01"}).status_code == 401


def test_role_change_applies_to_existing_cookie(server):
    """Roles are re-read on every request: a demoted user loses access at once."""
    username = uid("demoted")
    admin = login("admin")
    created = ok(admin.post("/admin/users", json={"username": username, "full_name": "x", "role": "training", "password": PASSWORD}))
    session = login(username)
    assert session.get("/admin/scenarios").status_code == 200
    ok(admin.put(f"/admin/users/{created['id']}", json={"full_name": "x", "role": "manager", "team_id": None, "is_active": True}))
    assert session.get("/admin/scenarios").status_code == 403
