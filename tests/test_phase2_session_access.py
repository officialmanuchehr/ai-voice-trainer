"""Phase 2 — session ownership / IDOR matrix for every session-scoped route.

Current policy (app/main.py `_load_session`), documented here, not changed:
  read  (transcript, score, audio): owner, sales lead of the owner's team, admin
  write (turn, voice turn, finish, score-run, dispute): owner only
Everyone else gets 403; an unknown session id gets 404 for everyone.
"""

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    archive_published_scenarios,
    finish_and_score,
    login,
    new_team_with_users,
    ok,
    say,
    server,
    start_session,
)

SEED_SCENARIO = "scn_merchant_onboarding_medium_01"
AUDIO = ("turn.webm", b"\x1a\x45\xdf\xa3 fake audio", "audio/webm")

READ_ROUTES = {
    "transcript": lambda c, sid: c.get(f"/sessions/{sid}/transcript"),
    "score": lambda c, sid: c.get(f"/sessions/{sid}/score"),
    "audio": lambda c, sid: c.get(f"/sessions/{sid}/turns/2/audio"),
}
WRITE_ROUTES = {
    "text turn": lambda c, sid: c.post(f"/sessions/{sid}/turns", json={"text": "чужая реплика"}),
    "voice turn": lambda c, sid: c.post(f"/sessions/{sid}/voice-turn", files={"audio": AUDIO}),
    "finish": lambda c, sid: c.post(f"/sessions/{sid}/finish"),
    "score-run": lambda c, sid: c.post(f"/sessions/{sid}/score-run"),
    "dispute": lambda c, sid: c.post(f"/sessions/{sid}/dispute", json={"comment": "чужое возражение"}),
}
# caller -> expected read status
READ_POLICY = {
    "owner": 200,
    "other_manager": 403,
    "same_team_lead": 200,
    "other_team_lead": 403,
    "training": 403,
    "product": 403,
    "compliance": 403,
    "admin": 200,
}
NON_OWNERS = [caller for caller in READ_POLICY if caller != "owner"]


@pytest.fixture(scope="module")
def people(server):
    team_a = new_team_with_users({"owner": "manager", "other_manager": "manager", "same_team_lead": "sales_lead"})
    team_b = new_team_with_users({"other_team_lead": "sales_lead"})
    return {**team_a, **team_b, "training": "trainer1", "product": "product1", "compliance": "compliance1", "admin": "admin"}


@pytest.fixture(scope="module")
def sessions(people):
    owner = login(people["owner"])
    active = start_session(owner, SEED_SCENARIO)["id"]
    say(owner, active)
    scored = start_session(owner, SEED_SCENARIO)["id"]
    say(owner, scored)
    finish_and_score(owner, scored)
    return {"active": active, "scored": scored}


def _state(session_id):
    owner_view = ok(login("admin").get(f"/sessions/{session_id}/transcript"))
    score = ok(login("admin").get(f"/sessions/{session_id}/score"))
    return len(owner_view["turns"]), owner_view["status"], score.get("dispute")


@pytest.mark.parametrize("route", READ_ROUTES)
@pytest.mark.parametrize("caller", READ_POLICY)
def test_read_routes(people, sessions, caller, route):
    response = READ_ROUTES[route](login(people[caller]), sessions["scored"])
    assert response.status_code == READ_POLICY[caller], response.text


@pytest.mark.parametrize("route", WRITE_ROUTES)
@pytest.mark.parametrize("caller", NON_OWNERS)
def test_write_routes_are_owner_only(people, sessions, caller, route):
    session_id = sessions["scored"] if route == "dispute" else sessions["active"]
    before = _state(session_id)
    response = WRITE_ROUTES[route](login(people[caller]), session_id)
    assert response.status_code == 403, (caller, route, response.status_code, response.text)
    assert _state(session_id) == before  # nothing recorded, no status change


def test_owner_can_use_every_write_route(people, server):
    owner = login(people["owner"])
    session_id = start_session(owner, SEED_SCENARIO)["id"]
    assert WRITE_ROUTES["text turn"](owner, session_id).status_code == 200
    assert WRITE_ROUTES["voice turn"](owner, session_id).status_code == 200
    assert WRITE_ROUTES["finish"](owner, session_id).status_code == 200
    assert WRITE_ROUTES["score-run"](owner, session_id).json()["status"] == "finished"
    assert WRITE_ROUTES["dispute"](owner, session_id).status_code == 200
    assert len(ok(owner.get(f"/sessions/{session_id}/transcript"))["turns"]) == 4


@pytest.mark.parametrize("route", [*READ_ROUTES, *WRITE_ROUTES])
@pytest.mark.parametrize("caller", ["owner", "same_team_lead", "admin", "training"])
def test_unknown_session_reveals_nothing(people, caller, route):
    routes = {**READ_ROUTES, **WRITE_ROUTES}
    response = routes[route](login(people[caller]), "0" * 32)
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_owner_history_lists_only_own_sessions(people, sessions):
    other = {row["id"] for row in ok(login(people["other_manager"]).get("/me/sessions"))}
    assert not other & set(sessions.values())
    own = {row["id"] for row in ok(login(people["owner"]).get("/me/sessions"))}
    assert set(sessions.values()) <= own


@pytest.mark.parametrize("caller,status", [("same_team_lead", 200), ("other_team_lead", 403), ("admin", 200), ("other_manager", 403), ("training", 403)])
def test_manager_drilldown_follows_team(people, sessions, caller, status):
    owner_id = next(u["id"] for u in ok(login("admin").get("/admin/users")) if u["username"] == people["owner"])
    response = login(people[caller]).get(f"/dashboard/managers/{owner_id}/sessions")
    assert response.status_code == status
    if status == 200:
        assert set(sessions.values()) <= {row["id"] for row in response.json()["sessions"]}
