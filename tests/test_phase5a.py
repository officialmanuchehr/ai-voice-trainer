"""Phase 5A — manager training experience.

Python checks (always run): the training page reads only manager-safe API
fields, never hidden scenario fields, and calls only known routes.
Node checks (run when Node is installed): the real result renderer
(resultHtml in static/app.js, a pure function) against stored-result
fixtures — cap explanation, critical errors, claim groups, escaping, and no
invented content when data is missing.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    archive_published_scenarios,
    login,
    ok,
    server,
)

STATIC = Path(__file__).resolve().parent.parent / "static"
TRAINING_JS = (STATIC / "js" / "pages" / "training.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
SEED_SCENARIO = "scn_merchant_onboarding_medium_01"

HIDDEN_FIELDS = [
    "client_profile", "variants", "pain", "hidden_need", "explicit_needs", "objections", "decision_criteria",
    "financial_literacy", "trust_level", "attitude_to_bank", "emotion", "urgency", "turnover",
    "business_context", "current_products", "good_examples", "feedback_hints", "criteria_weights",
]


# ------------------------------------------------------------ safe data only


@pytest.mark.parametrize("field", HIDDEN_FIELDS)
def test_training_page_never_references_hidden_fields(field):
    for name, source in (("training.js", TRAINING_JS), ("app.js", APP_JS)):
        assert not re.search(rf"\.{field}\b|\[['\"]{field}['\"]\]", source), f"{name} reads hidden field {field}"


def _fields_read(function_name, variable):
    body = re.search(rf"function {function_name}\([^)]*\) \{{(.*?)\n\}}", TRAINING_JS, re.S).group(1)
    return set(re.findall(rf"\b{variable}\.([a-z_]+)\b", body))


def test_briefing_and_catalogue_read_only_catalogue_fields(server):
    item = next(s for s in ok(login("manager1").get("/scenarios")) if s["id"] == SEED_SCENARIO)
    read = _fields_read("openBriefing", "s") | _fields_read("renderCards", "s")
    assert read <= set(item), read - set(item)
    assert {"title", "goal", "difficulty", "product_name", "briefing"} <= read


def test_session_start_reads_only_session_response_fields(server):
    session = ok(login("manager1").post("/sessions", json={"scenario_id": SEED_SCENARIO}))
    read = _fields_read("startSession", "data")
    assert read <= set(session), read - set(session)


def test_client_identity_comes_from_the_visible_briefing_only(server):
    """The name shown as the client is the briefing's 'Клиент' entry — a field
    the API already exposes to managers — or a neutral 'AI-клиент'."""
    assert "visible['Клиент']" in TRAINING_JS and "'AI-клиент'" in TRAINING_JS
    session = ok(login("manager1").post("/sessions", json={"scenario_id": SEED_SCENARIO}))
    assert {b["label"] for b in session["briefing"]} <= {
        "Клиент", "Тип бизнеса", "Отрасль", "Размер компании", "Сотрудников", "Роль собеседника", "Текущий банк", "Ситуация",
    }


def test_training_page_calls_only_known_routes():
    called = {re.sub(r"\$\{[^}]+\}", "{}", p) for p in re.findall(r"(?:api|fetch)\(\s*`?['\"]?(/[^`'\"?]*)", TRAINING_JS)}
    allowed = {
        "/scenarios", "/me/sessions", "/sessions", "/sessions/{}/turns", "/sessions/{}/voice-turn",
        "/sessions/{}/transcript", "/sessions/{}/score", "/sessions/{}/finish", "/sessions/{}/score-run",
        "/sessions/{}/dispute",
    }
    assert called <= allowed, called - allowed


def test_page_structure_for_the_journey(server):
    html = server.get("/").text
    for marker in (
        'id="briefing-dlg" aria-labelledby="briefing-title"',
        'id="finish-dlg" aria-labelledby="finish-title" aria-describedby="finish-text"',
        'role="timer"',
        'id="voice-state" data-state="ready" role="status" aria-live="polite"',
        'id="scoring" role="status" aria-live="polite"',
        'id="mic-btn" aria-pressed="false"',
        'id="result" tabindex="-1"',
    ):
        assert marker in html, marker


def test_phase3a_recovery_kept_and_scoring_failure_handled():
    for marker in ("async function syncChat()", "async function turnFailed(", "manager_text", "audio_error", "retry.textContent = 'Повторить'"):
        assert marker in TRAINING_JS, marker
    assert "data.status === 'finish_error'" in TRAINING_JS and "scoring-retry" in TRAINING_JS
    # Timer is display-only: never sent to the server, never ends the session.
    timer_code = re.search(r"function startTimer\(\) \{(.*?)\n\}", TRAINING_JS, re.S).group(1)
    assert "api(" not in timer_code and "finishSession" not in timer_code


# ------------------------------------------------------------ result renderer (Node)

NODE = shutil.which("node")

CAPPED = {
    "total": 60, "scenario_version": 3, "kb_version": "1.2.0", "rubric_id": "rubric_sales_100",
    "cap_reason": {"limit": 60, "calculated_total": 82, "triggers": [
        {"kind": "claim", "verdict": "unapproved", "claim_text": "Лимит 500 000 без комиссии", "turn_index": 3, "reason": "нет в БЗ"},
        {"kind": "critical_error", "type": "Обещание тарифа, которого нет в БЗ.", "quote": "q", "explanation": "e"},
    ]},
    "critical_errors": [{"type": "Обещание тарифа, которого нет в БЗ.", "quote": "Лимит 500 000 без комиссии", "explanation": "Такого условия нет в базе знаний."}],
    "claim_checks": [
        {"turn_index": 1, "claim_text": "Подключение бесплатное", "verdict": "approved", "reason": "fact_free_connection"},
        {"turn_index": 3, "claim_text": "Лимит 500 000 без комиссии", "verdict": "unapproved", "reason": "нет в БЗ"},
        {"turn_index": 5, "claim_text": 'Гарантирую "одобрение" <сразу>', "verdict": "forbidden", "reason": "запрещено"},
    ],
    "breakdown": [{"criterion_id": "contact", "score": 8, "max": 10, "reason": "Хороший контакт", "quote": "Добрый день"}],
    "feedback": {"summary": "Главный вывод.", "strengths": ["Сильная сторона"], "growth_areas": ["Зона роста"],
                 "better_examples": [{"was": "было", "better": "лучше"}], "next_skill": "Выявление потребностей"},
}
MINIMAL = {"total": 47, "scenario_version": 1, "kb_version": "1.0.0", "cap_reason": None, "critical_errors": [],
           "claim_checks": [], "breakdown": [], "feedback": {}}


def _render(payload):
    script = f"""
const vm = require('vm');
const ctx = {{}};
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync({json.dumps(str(STATIC / 'app.js'))}, 'utf8') + ';this.resultHtml = resultHtml;', ctx);
process.stdout.write(ctx.resultHtml({json.dumps(payload, ensure_ascii=False)}, {{ contact: 'Установление контакта' }}));
"""
    return subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout


needs_node = pytest.mark.skipif(NODE is None, reason="Node not installed; renderer is also covered by the browser review")


@needs_node
def test_capped_result_explains_the_cap():
    html = _render(CAPPED)
    assert "Итог ограничен 60 баллами." in html and "Без ограничения было бы 82" in html
    assert "Нет в утверждённой базе знаний" in html and '<a href="#turn-3">Реплика 3</a>' in html
    assert "Критичная ошибка: Обещание тарифа, которого нет в БЗ." in html


@needs_node
def test_critical_errors_are_shown_with_quote_and_explanation():
    html = _render(CAPPED)
    assert "Что нужно исправить в первую очередь" in html
    assert "«Лимит 500 000 без комиссии»" in html and "Такого условия нет в базе знаний." in html


@needs_node
def test_claims_are_grouped_by_verdict_riskiest_first_and_escaped():
    html = _render(CAPPED)
    positions = [html.index(label) for label in ("Запрещённые формулировки", "Нет в утверждённой базе знаний</span>", "Подтверждено базой знаний")]
    assert positions == sorted(positions)
    assert "«Гарантирую &quot;одобрение&quot; &lt;сразу&gt;»" in html
    assert '<a href="#turn-5">Реплика 5</a>' in html and "версия 1.2.0" in html


@needs_node
def test_result_keeps_versions_and_main_takeaway():
    html = _render(CAPPED)
    assert "Сценарий v3 · база знаний v1.2.0 · рубрика rubric_sales_100" in html
    assert '<p class="takeaway">Главный вывод.</p>' in html and "Выявление потребностей" in html
    assert "«было»" in html and "«лучше»" in html and "Установление контакта" in html


def _render_with_defaults(payload, defaults):
    script = f"""
const vm = require('vm');
const ctx = {{}};
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync({json.dumps(str(STATIC / 'app.js'))}, 'utf8') + ';this.resultHtml = resultHtml;', ctx);
process.stdout.write(ctx.resultHtml({json.dumps(payload, ensure_ascii=False)}, {{}}, {json.dumps(defaults)}));
"""
    return subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout


@needs_node
def test_weight_note_only_for_real_scenario_overrides():
    row = {"criterion_id": "needs", "score": 50, "max": 100, "weight": 15, "reason": "r"}
    assert "вес в этом сценарии" not in _render_with_defaults({**MINIMAL, "breakdown": [row]}, {"needs": 15})
    html = _render_with_defaults({**MINIMAL, "breakdown": [{**row, "weight": 40}]}, {"needs": 15})
    assert "вес в этом сценарии: 40 вместо 15" in html


@needs_node
def test_minimal_result_invents_nothing():
    html = _render(MINIMAL)
    for absent in ("Итог ограничен", "Что нужно исправить", "Что получилось", "Как сказать лучше", "Оценка по критериям", "takeaway", "Что тренировать дальше"):
        assert absent not in html, absent
    assert "Конкретных утверждений о продукте в разговоре не найдено." in html
    assert "undefined" not in html and "null" not in html and "NaN" not in html
    assert ">47<small> / 100</small>" in html
