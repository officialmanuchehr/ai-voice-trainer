"""Security hotfix — HTML output escaping (stored attribute injection).

Root cause: esc() was DOM-based (textContent -> innerHTML), which escapes
& < > but not quotes, so stored text placed in title="…", value="…" or
data-*="…" could break out of the attribute. CSP is defence in depth only;
these tests prove the generated HTML itself is safe.

Level A (always runs, no Node): the escaping contract read from the real
static/app.js source, replayed in Python, plus a guard that every
attribute-context interpolation in the frontend goes through esc() or is a
known-safe value.
Level B (runs when Node is installed): the real esc() executed in Node.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")

PAYLOADS = [
    'x" autofocus onfocus="alert(1)',
    "x' autofocus onfocus='alert(1)",
    '"><img src=x onerror=alert(1)>',
    "'><svg onload=alert(1)>",
    '&quot; already-encoded &amp; text',
    "Кафе «У Ашота» & Co's \"Best\" <1>",
]
EXPECTED = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
}


# ----------------------------------------------------------------- Level A


def _esc_source():
    match = re.search(r"function esc\(s\) \{(.*?)\n\}", APP_JS, re.S)
    assert match, "esc() not found in static/app.js"
    return match.group(1)


def _escape_table():
    match = re.search(r"const HTML_ESCAPES = (\{[^}]*\});", APP_JS)
    assert match, "HTML_ESCAPES table not found in static/app.js"
    pairs = re.findall(r"""(['"])(.+?)\1\s*:\s*(['"])(.+?)\3""", match.group(1))
    return {key: value for _, key, _, value in pairs}


def test_esc_does_not_use_the_dom():
    body = _esc_source()
    for dom_api in ("document", "createElement", "innerHTML", "textContent"):
        assert dom_api not in body, f"esc() must not rely on {dom_api}"


def test_escape_table_covers_all_five_characters_with_correct_entities():
    assert _escape_table() == EXPECTED


def test_esc_replaces_every_special_character_in_a_single_pass():
    body = _esc_source()
    regex = re.search(r"\.replace\(/(\[[^\]]+\])/g,", body)
    assert regex, "esc() must use one global character-class replace"
    char_class = regex.group(1)
    for ch in EXPECTED:
        assert ch in char_class, f"{ch!r} missing from esc() character class"
    assert body.count(".replace(") == 1, "chained replaces risk double-escaping; use one pass"
    assert "HTML_ESCAPES[ch]" in body


def _python_esc(value):
    """The rule read from app.js, replayed: one pass over the five characters."""
    table = _escape_table()
    return re.sub(r"[&<>\"']", lambda m: table[m.group(0)], "" if value is None else str(value))


@pytest.mark.parametrize("payload", PAYLOADS)
def test_payloads_cannot_leave_a_quoted_attribute(payload):
    escaped = _python_esc(payload)
    for raw in ('"', "'", "<", ">"):
        assert raw not in escaped
    # Single pass: each produced entity appears exactly once per source character.
    assert escaped.count("&quot;") == payload.count('"') and escaped.count("&#39;") == payload.count("'")
    # Inside a double- and a single-quoted attribute the value stays one token.
    for quote in ('"', "'"):
        html = f"<div title={quote}{escaped}{quote}>"
        assert html.count(quote) == 2


def test_legitimate_text_round_trips_through_the_browser_decoding():
    import html

    for text in ("Кафе «У Ашота» & Co's \"Best\" <1>", "Don't", '5 > 3 & "ok"', "", "Simple"):
        assert html.unescape(_python_esc(text)) == text  # what the user sees == what was stored


# -------- guard: every attribute-context interpolation is escaped or known-safe


def _attribute_interpolations():
    """(file, attribute, expression) for every ${…} inside a quoted HTML
    attribute in a JS template literal under static/."""
    found = []
    for path in sorted(STATIC.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'([a-zA-Z-]+)=(["\'])([^"\'<>]*?)\$\{', text):
            start = match.end()
            depth, i = 1, start
            while i < len(text) and depth:
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                i += 1
            found.append((path.relative_to(STATIC).as_posix(), match.group(1), text[start:i - 1].strip()))
    return found


# Expressions that may appear unescaped inside an attribute: numbers, enums
# and constants produced by the code itself, never stored user text.
KNOWN_SAFE = {
    "to", "v.version", "d", "w[c.id] ?? c.weight", "t.id", "k", "id", "kind", "i",
    "u.is_active ? '' : 'muted'", "scoreClass(data.total)",
    "Math.max(0, Math.min(100, v / max * 100))",
    "L", "L - 6", "W - R", "y(v)", "y(v) + 4", "x(i)", "H - 8", "y(p.avg_score)", "x(i) - 18", "T",
    "H - T - B", "W", "H", "y(60)", "y(60) - 4", "path",
    # Phase 5A result renderer: CSS classes from code constants and numbers.
    "scoreClass(total)",                 # 'low' | 'high'
    "Number(total) || 0", "pct",         # numbers computed in code
    "VERDICTS[g.verdict].badge",         # constant map in app.js
}
SAFE_WRAPPERS = ("esc(", "encodeURIComponent(", "fmtDate(")


def test_every_attribute_interpolation_is_escaped_or_known_safe():
    unsafe = []
    for file, attribute, expression in _attribute_interpolations():
        if expression.startswith(SAFE_WRAPPERS) or expression in KNOWN_SAFE:
            continue
        if file == "theme.js" and expression in ("id",):
            continue
        unsafe.append(f"{file}: {attribute}=\"${{{expression}}}\"")
    assert not unsafe, "unescaped data in HTML attributes:\n" + "\n".join(unsafe)


def test_the_previously_vulnerable_sinks_now_go_through_the_fixed_esc():
    # Phase 7 replaced the admin JSON dialogs with structured editors: every
    # stored value reaches the page through FormBinder's escaped controls.
    editor = (STATIC / "js" / "content-editor.js").read_text(encoding="utf-8")
    kb = (STATIC / "js" / "kb-editor.js").read_text(encoding="utf-8")
    scenario = (STATIC / "js" / "scenario-editor.js").read_text(encoding="utf-8")
    shell = (STATIC / "js" / "shell.js").read_text(encoding="utf-8")
    for needle in (
        'value="${esc(value)}"',                     # every text input (titles, ids, notes …)
        '>${esc(value)}</textarea>',                 # every textarea (facts, responses, notes …)
        '<option value="${esc(value)}"',             # select options
    ):
        assert needle in editor, needle
    assert "v${esc(ver.version)}" in kb and "esc(ver.author || '—')" in kb   # KB version / author
    assert "esc(ver.notes || '—')" in kb                                        # KB notes
    assert "esc(st.meta.author || '—')" in scenario                             # scenario author
    assert 'title="${esc(me.full_name || me.username)}' in shell  # full name
    assert "esc(me.team_name)" in shell                            # team name


# ----------------------------------------------------------------- Level B


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node not installed; Level A tests still protect the contract")
def test_real_esc_executed_in_node():
    script = f"""
const vm = require('vm');
const ctx = {{}};
vm.createContext(ctx);
vm.runInContext(require('fs').readFileSync({json.dumps(str(STATIC / 'app.js'))}, 'utf8') + ';this.esc = esc;', ctx);
const inputs = {json.dumps(PAYLOADS + ["&", "<", ">", '"', "'", "&<>\"'", None])}.concat([undefined, 42]);
process.stdout.write(JSON.stringify(inputs.map((v) => ctx.esc(v))));
"""
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    results = json.loads(out)
    singles = results[len(PAYLOADS):len(PAYLOADS) + 6]
    assert singles == ["&amp;", "&lt;", "&gt;", "&quot;", "&#39;", "&amp;&lt;&gt;&quot;&#39;"]
    assert results[-3:] == ["", "", "42"]
    for payload, escaped in zip(PAYLOADS, results):
        assert escaped == _python_esc(payload)  # Node and the Level A replay agree
        assert not set('"\'<>') & set(escaped)
    assert results[0] == "x&quot; autofocus onfocus=&quot;alert(1)"
    assert results[1] == "x&#39; autofocus onfocus=&#39;alert(1)"
