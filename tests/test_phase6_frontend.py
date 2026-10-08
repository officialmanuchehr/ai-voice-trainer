"""Phase 6 — lead pages (Обзор, Команда, manager drill-down): routes, APIs,
no analytics math or ranking language in JS, no thresholds or flags."""

import json
import re
from pathlib import Path

import pytest
from support import login, server  # noqa: F401  (server is a fixture)

STATIC = Path(__file__).resolve().parent.parent / "static"
PAGES = {"team": "/team", "manager": "/manager"}


def script(name):
    return (STATIC / "js" / "pages" / f"{name}.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("name,route", PAGES.items())
def test_pages_are_served(server, name, route):
    html = login("lead1").get(route).text
    assert f'<script src="/static/js/pages/{name}.js"></script>' in html


@pytest.mark.parametrize("name,allowed", [
    ("team", {"/dashboard/data"}),
    ("manager", {"/dashboard/managers/${encodeURIComponent(id)}/progress", "/dashboard/managers/${encodeURIComponent(id)}/sessions"}),
    ("dashboard", {"/dashboard/data", "/products"}),
])
def test_pages_call_only_scoped_endpoints(name, allowed):
    calls = set(re.findall(r"api\(['`]([^'`?]+)", script(name)))
    assert calls == allowed, calls


@pytest.mark.parametrize("name", ["team", "manager", "dashboard"])
def test_no_analytics_math_ranking_or_thresholds(name):
    source = script(name)
    for pattern in (r"\.reduce\(", r"\.sort\(", r"Math\.round", r"avg_pct\s*[<>]", r"avg_score\s*[<>]", r"critical_rate\s*>=", r"⚠", "needs_help", "reasons"):
        assert not re.search(pattern, source), (name, pattern)
    lowered = source.lower()
    for word in ("рейтинг", "лидер", "лучш", "худш", "топ-", "риск", "отстающ", "порог", "требует внимания", "плохо"):
        assert word not in lowered, (name, word)


def test_dashboard_has_no_reference_threshold_line_or_recommendations():
    source = script("dashboard")
    html = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    assert "ref-line" not in source and "порог" not in source
    assert "recommendations" not in source and "recommendations" not in html
    assert "ниже 60" not in html and "⚠" not in html
    assert "Самый низкий средний результат среди критериев" in source


def test_team_order_is_explained_as_alphabetical_and_not_an_assessment():
    source = script("team")
    assert "по алфавиту" in source and "не оценка сотрудника" in source


def test_lead_navigation():
    nav = json.loads((STATIC / "js" / "nav.json").read_text(encoding="utf-8"))
    items = [i for g in nav["groups"] for i in g["items"]]
    lead = [i["key"] for i in items if "sales_lead" in i["roles"]]
    assert lead == ["dashboard", "team", "train", "history"]
    team = next(i for i in items if i["key"] == "team")
    assert team["href"] == "/team"


def test_drilldown_links_are_escaped_and_session_actions_are_read_only():
    for name in ("team", "manager", "dashboard"):
        source = script(name)
        assert "?repeat=" not in source  # no training actions on someone else's session
        assert "/dispute" not in source
    assert 'href="/manager?id=${esc(encodeURIComponent(m.user_id))}"' in script("team")
