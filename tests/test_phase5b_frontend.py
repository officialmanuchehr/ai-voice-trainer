"""Phase 5B — Overview, My Progress and History pages: served routes, the
APIs they call, presentation-only rule (no analytics math in JS), repeat
link into the 5A briefing, and nothing private in the served pages.
"""

import re
from pathlib import Path

import pytest
from support import login, server  # noqa: F401  (server is a fixture)

STATIC = Path(__file__).resolve().parent.parent / "static"
PAGES = {"overview": "/overview", "progress": "/progress", "history": "/history"}


def script(name):
    return (STATIC / "js" / "pages" / f"{name}.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("name,route", PAGES.items())
def test_pages_are_served_with_their_script(server, name, route):
    html = login("manager1").get(route)
    assert html.status_code == 200
    assert f'<script src="/static/js/pages/{name}.js"></script>' in html.text
    assert "Начать тренировку" in html.text


@pytest.mark.parametrize("name,allowed", [
    ("overview", {"/me/progress", "/me/sessions"}),
    ("progress", {"/me/progress"}),
    ("history", {"/me/sessions"}),
])
def test_pages_call_only_the_callers_own_endpoints(name, allowed):
    calls = set(re.findall(r"api\(['`]([^'`$?]+)", script(name)))
    assert calls == allowed
    assert not re.search(r"user_id|manager_id|team_id|username", script(name))


@pytest.mark.parametrize("name", [*PAGES, "../progress-view"])
def test_no_analytics_math_in_javascript(name):
    """The backend owns averages, normalisation, ranking and grouping."""
    source = script(name)
    for pattern in (r"\.reduce\(", r"\.sort\(", r"/\s*p\.sessions", r"\bsum\b", r"Math\.round", r"latest_score\s*-", r"avg_pct\s*[*/]"):
        assert not re.search(pattern, source), (name, pattern)


def test_history_repeat_opens_the_5a_briefing_and_unavailable_is_explained():
    source = script("history")
    assert 'href="/?repeat=${esc(encodeURIComponent(s.scenario_id))}"' in source
    assert "сценарий недоступен" in source
    assert "scenario_available" in source
    assert "repeat" in (STATIC / "js" / "pages" / "training.js").read_text(encoding="utf-8")


def test_next_skill_is_labelled_as_evaluator_feedback_not_a_plan():
    source = script("overview")
    assert "Совет из оценки тренировки от" in source
    for word in ("персональн", "адаптив", "рекомендуем", "цель", "рейтинг", "уровень готовности"):
        assert word not in source.lower(), word


def test_progress_has_text_equivalents_and_no_target_line():
    source = (STATIC / "js" / "progress-view.js").read_text(encoding="utf-8")  # shared with the Phase 6 drill-down
    assert 'role="img"' in source and "aria-label" in source
    assert "<details" in source and "<table>" in source
    assert "ref-line" not in source and "порог" not in source


def test_status_is_shown_as_text_not_colour_only():
    source = script("history")
    assert "SESSION_STATUS[status]" in source
    assert "критичная ошибка" in source


def test_training_page_no_longer_loads_history():
    assert "/me/sessions" not in (STATIC / "js" / "pages" / "training.js").read_text(encoding="utf-8")
    assert 'href="/history"' in (STATIC / "index.html").read_text(encoding="utf-8")


def test_manager_lands_on_overview():
    assert "{ manager: '/overview', sales_lead: '/dashboard' }[user.role] || '/'" in (STATIC / "js" / "pages" / "login.js").read_text(encoding="utf-8")


def test_anonymous_gets_only_the_static_shell_and_no_data(server):
    """Pages are static (the JS redirects to /login on 401); the data is
    behind the role-checked API."""
    from fastapi.testclient import TestClient

    from app.main import app

    anonymous = TestClient(app)
    for route in PAGES.values():
        assert anonymous.get(route).status_code == 200
    for endpoint in ("/me/progress", "/me/sessions"):
        assert anonymous.get(endpoint).status_code == 401
