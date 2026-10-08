"""Phase 7 — structured content editors (frontend). Static checks always
run; the content-model / FormBinder checks execute the real JS in Node
(skipped when Node is absent)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from support import login, server  # noqa: F401  (server is a fixture)

from app.content import _REVIEWABLE_KB_SECTIONS, _TRANSITIONS, kb_review_blockers

STATIC = Path(__file__).resolve().parent.parent / "static"
SEED = Path(__file__).resolve().parent.parent / "seed"
JS = {name: (STATIC / "js" / f"{name}.js").read_text(encoding="utf-8") for name in ("content-model", "content-editor", "scenario-editor", "kb-editor")}
ADMIN = (STATIC / "js" / "pages" / "admin.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def test_admin_page_loads_editor_modules_in_order(server):
    html = login("admin").get("/admin").text
    order = re.findall(r'<script src="([^"]+)"', html)
    assert order[-5:] == ["/static/js/content-model.js", "/static/js/content-editor.js", "/static/js/scenario-editor.js", "/static/js/kb-editor.js", "/static/js/pages/admin.js"]


def test_no_editable_raw_json_and_no_browser_prompts():
    everything = "".join(JS.values()) + ADMIN
    assert "JSON.parse($(" not in everything            # nothing reads JSON typed by a user
    assert '<textarea class="code' not in everything    # old editable JSON textareas are gone
    assert "Технический вид (JSON, только чтение)" in JS["scenario-editor"] and "Технический вид (JSON, только чтение)" in JS["kb-editor"]
    assert not re.search(r"\b(prompt|confirm|alert)\(", everything.replace("confirmDialog(", "").replace("confirmLeave(", "").replace("confirmTransition(", ""))


def test_new_product_dialog_prefills_no_bank_content():
    source = JS["kb-editor"]
    block = source[source.index("function newProductDialog"):]
    assert 'id="np-fact" required rows="3"></textarea>' in block  # empty fact text
    for invented in ("сомони", "комисси", "%", "ставк", "condition"):
        assert invented not in block.lower(), invented


def test_frontend_lifecycle_mirrors_backend():
    model = JS["content-model"]
    for status, targets in _TRANSITIONS.items():
        block = re.search(rf"{status}: \[(.*?)\]\s*,?\n", model).group(1) if targets else ""
        assert set(re.findall(r"\['(\w+)'", block)) == targets, status
    assert re.search(r"KB_REVIEW_SECTIONS = \[(.*?)\]", model).group(1).replace("'", "").split(", ") == list(_REVIEWABLE_KB_SECTIONS)


def test_editor_labels_distinguish_blocker_from_guidance():
    kb = JS["kb-editor"]
    assert "Требует проверки — блокирует утверждение и публикацию" in kb
    assert "Комментарий комплаенса (справочно, сам по себе не блокирует)" in kb
    assert "Формулировка за комплаенсом" in kb
    assert "Снять пометку черновика" in kb


def test_scenario_editor_separates_visible_hidden_internal():
    s = JS["scenario-editor"]
    for heading in ("Видит менеджер", "Скрыто от менеджера — профиль AI-клиента", "Обучение и оценка (внутреннее)"):
        assert heading in s
    assert "base_version: st.version" in s  # stale new-version can't overwrite a newer draft


def test_consequential_actions_are_confirmed():
    assert "confirmTransition('scenario'" in JS["scenario-editor"] and "confirmTransition('kb'" in JS["kb-editor"]
    assert "Вернуть её из архива нельзя" in JS["scenario-editor"]
    assert "станет действующей базой знаний продукта" in JS["scenario-editor"]


# ------------------------------------------------------------ executed in Node


def run_node(body: str):
    script = "const vm = require('vm'); const fs = require('fs'); const ctx = {}; vm.createContext(ctx);\n"
    for path in ("app.js", "js/content-model.js"):
        script += f"vm.runInContext(fs.readFileSync({json.dumps(str(STATIC / path))}, 'utf8'), ctx);\n"
    editor = JS["content-editor"].split("// ------------------------------------------------------------ confirm dialog")[0]
    script += f"vm.runInContext({json.dumps(editor)} + ';this.FormBinder = FormBinder; this.readOnlyFields = readOnlyFields;', ctx);\n"
    script += f"const out = vm.runInContext({json.dumps(body)}, ctx); process.stdout.write(JSON.stringify(out));"
    return json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout)


node = pytest.mark.skipif(NODE is None, reason="Node not installed")
SEED_KB = json.loads((SEED / "knowledge_base.json").read_text(encoding="utf-8"))["products"]
SEED_SCN = json.loads((SEED / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]


@node
def test_display_blockers_equal_backend_blockers_for_every_seed_kb():
    got = run_node(f"{json.dumps(SEED_KB)}.map((p) => kbBlockers(p))")
    assert got == [kb_review_blockers(p) for p in SEED_KB]


@node
def test_seed_content_passes_frontend_checks_unchanged():
    kb = run_node(f"{json.dumps(SEED_KB)}.map((p) => kbProblems(p))")
    scn = run_node(f"{json.dumps(SEED_SCN)}.map((s) => scenarioProblems(s))")
    assert kb == [[] for _ in SEED_KB] and scn == [[] for _ in SEED_SCN]


@node
def test_profile_rows_keep_every_key_including_base_plus_variants():
    catalogue = [{"id": "persona_name", "label": "имя", "briefing": True, "list": False}, {"id": "business_type", "label": "тип", "briefing": True, "list": False},
                 {"id": "pain", "label": "боль", "briefing": False, "list": False}, {"id": "objections", "label": "возражения", "briefing": False, "list": True}]
    profile = {"pain": "p", "business_type": "b", "custom": {"x": 1}, "objections": ["a", "b"], "variants": {"business_type": ["b1", "b2"], "persona_name": ["Фарход"], "other_var": ["o"]}}
    rows = run_node(f"profileRows({json.dumps(profile)}, {json.dumps(catalogue)})")
    assert [r["key"] for r in rows] == ["persona_name", "business_type", "pain", "objections", "custom", "other_var"]
    bt = next(r for r in rows if r["key"] == "business_type")
    assert bt["hasBase"] and bt["hasVariants"] and bt["briefing"]
    assert next(r for r in rows if r["key"] == "custom")["known"] is False


@node
def test_typed_values_keep_numbers_numbers():
    got = run_node("[typedValue(100000, '150000'), typedValue(0, '0'), typedValue(5, ''), typedValue(5, 'abc'), typedValue('TJS', 'USD'), typedValue(true, false)]")
    assert got == [150000, 0, "", "abc", "USD", False]


@node
def test_binder_edits_exactly_one_path_and_leaves_the_rest_identical():
    fact = SEED_KB[0]["approved_facts"]
    body = f"""
      const data = {json.dumps(SEED_KB[0])};
      const before = JSON.stringify(data);
      const root = {{ addEventListener() {{}}, contains() {{ return true; }} }};
      const b = new FormBinder(root, () => {{}});
      const fact = data.approved_facts.find((f) => f.value);
      b.text('limit', () => fact.value.limit, (v) => {{ fact.value.limit = typedValue(fact.value.limit, v); }});
      b.bindings[0].set('200000');
      [before, JSON.stringify(data), typeof fact.value.limit]
    """
    before, after, kind = run_node(body)
    expected = json.loads(before)
    next(f for f in expected["approved_facts"] if f.get("value"))["value"]["limit"] = 200000
    assert json.loads(after) == expected and kind == "number"


@node
@pytest.mark.parametrize("payload", ['x" autofocus onfocus="alert(1)', "'><img src=x onerror=alert(1)>", "</textarea><script>alert(1)</script>"])
def test_form_controls_escape_stored_content(payload):
    html = run_node(f"""
      const root = {{ addEventListener() {{}}, contains() {{ return true; }} }};
      const b = new FormBinder(root, () => {{}});
      const v = {json.dumps(payload)};
      [b.text('Метка ' + v, () => v, () => {{}}), b.text('t', () => v, () => {{}}, {{ multiline: true }}),
       b.select('s', [[v, v]], () => v, () => {{}}), b.checkbox(v, () => true, () => {{}}),
       b.stringList(v, () => [v], () => {{}}, {{ key: v }}), readOnlyFields({{ [v]: v }}, [v])].join('')
    """)
    assert "<img" not in html and "<script" not in html and "</textarea><script" not in html
    assert 'onfocus="alert' not in html and "onerror=alert" not in html.replace("onerror=alert(1)&gt;", "")
