# Security hotfix — HTML attribute escaping

**Date:** 2026-10-05 · **Base:** Phase 4A `1ee20e4` · **Scope:** one frontend function plus tests. Found during Phase 5A preparation, before any Phase 5A code was written.

## Root cause
- **The old function:** `esc()` in `static/app.js` escaped by assigning to `textContent` and reading `innerHTML`. HTML serialisation of a text node escapes only `&`, `<`, `>` (and NBSP), **not `"` or `'`**.
- **Why that mattered:** that's safe between tags, but the frontend also places `esc()` output inside quoted attributes (`value="…"`, `title="…"`, `data-*="…"`). A stored value containing `"` therefore ended the attribute and could add new ones.
- **Proof in Chrome against the old code:** a scenario title `x" autofocus onfocus="…` was parsed as real `autofocus=""` and `onfocus="…"` attributes on the admin title field.
- **Legitimate text broke too:** a title containing `"Best"` produced junk attributes, and the editor showed a **truncated** value; saving would have stored the truncation.

## Why CSP alone was insufficient
- **The Phase 4A CSP** (`script-src 'self'`, no `'unsafe-inline'`) blocks injected **event handlers**. It does **not** block injected non-script attributes (`autofocus`, `hidden`, `disabled`, `form`, …), broken or truncated values, or the data-loss effect above.
- **Production has no CSP at all:** it still runs pre-Phase-1 code. There the bug was an exploitable stored XSS by a privileged insider (training, product or compliance editors, or an admin-set name or team) against anyone opening the affected screen.
- **The rule:** escaping is the boundary; CSP is the second layer.

## Complete frontend sink audit (`static/`)

| Item | Result |
|---|---|
| Sink APIs | 50 `innerHTML` assignments (45 `=`, 4 `+=` for `<option>` lists, 1 in `theme.js`). **No** `outerHTML`, `insertAdjacentHTML`, `document.write`, `DOMParser`, `srcdoc`, `eval`, `new Function`, or `setAttribute` of `on*`/`href`/`src`/`style`. |
| `esc(` occurrences | 156 (including the definition) |
| Template interpolations | 382 `${…}` inside JS template literals (tokenised with nesting), 64 in attribute context |
| Wrapped by an encoder | 174 (`esc`, `encodeURIComponent`, `fmtDate`) |
| Not wrapped, reviewed one by one | 162 direct + nested templates, all safe: server numbers (scores, counts, versions, IDs, SVG coordinates); code-side constants and enums (labels, CSS classes, `selected`/`checked`/`readonly`, role and theme keys, icon markup); helpers that escape internally (`capNote`, `list`, `statusChip`, `scenarioForm`, `stateHtml`); non-HTML uses (API URL paths, `<audio>.src`, `textContent` via `setPageHeader` / `addBubble`) |
| Error messages | Every `err.message` / `detail` reaches the page via `textContent` or `esc()` |
| JavaScript context | None (no inline scripts or handlers since Phase 4A) |
| URL context | `href="/session?id=${encodeURIComponent(…)}"` (double-quoted, so the unencoded `'` is harmless); nav `href` from static `nav.json` |
| Style context | None in markup; dashboard widths via CSSOM from numbers |

**Attribute sinks carrying user-editable text** (all fixed by the new `esc()`):

| Field | Sink |
|---|---|
| Scenario title | `admin.js` `value="…"` |
| Scenario learning goal | `admin.js` `value="…"` |
| KB version notes | `admin.js` `value="…"` |
| KB version string | `admin.js` `data-kbver="…"` |
| Author username | `admin.js` `title="…"` |
| User full name, team name | `shell.js` `title="…"` |

Other attribute values are server-generated IDs, enums or validated product IDs; also safe now.

**No other injection class was found.**

## Exact fix
```js
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (ch) => HTML_ESCAPES[ch]);
}
```
- **Pure string**, no DOM.
- **One pass:** each character is replaced exactly once, so produced entities are never re-escaped.
- **One function** for text and attributes.
- **Same behaviour** for `null`/`undefined` (empty) and numbers (stringified).
- **Not changed:** backend, stored data (raw content stays raw; escaping happens at output), CSP.

## Tests (`tests/test_security_html_escaping.py`, 13)

**Level A — mandatory, runs without Node (12 tests):**
- the real `esc()` source uses no DOM;
- its escape table is exactly the five characters with the correct entities;
- a single global character-class replace (no chained replaces);
- the extracted rule, replayed in Python, keeps 6 attack and legitimate payloads inside both `"…"` and `'…'` attributes;
- legitimate text round-trips through browser decoding unchanged (no double escaping);
- **a guard over every attribute-context interpolation in `static/`**: anything not passed through `esc()` / `encodeURIComponent()` / `fmtDate()` must be on a reviewed known-safe list, so a future raw insertion fails the suite;
- the seven previously vulnerable sinks still route through `esc()`.

**Level B — Node behavioural (1 test, skips only if Node is absent):** executes the real `static/app.js` in a Node `vm` context. Exact outputs:

| Input | Output |
|---|---|
| `&` | `&amp;` |
| `<` | `&lt;` |
| `>` | `&gt;` |
| `"` | `&quot;` |
| `'` | `&#39;` |
| `&<>"'` | `&amp;&lt;&gt;&quot;&#39;` |
| `null` / `undefined` | `""` |
| `42` | `"42"` |
| `x" autofocus onfocus="alert(1)` | `x&quot; autofocus onfocus=&quot;alert(1)` |

Node's output matches the Level A replay for every payload.

**Proof the tests guard the fix:**
- against the **old** `esc()`: **11 failed, 2 passed** (the 2 that pass don't depend on how `esc()` is implemented);
- with **Node hidden from PATH**: 12 passed, 1 skipped.

## Real-browser verification (Level C, scratchpad only)
Real Chrome (headless) via Playwright from the scratchpad virtualenv; not a project dependency. Local server, stub providers.
- **Stored through the real API:**
  - a training user (with a malicious full name and team) saved a scenario with payload title and learning goal;
  - a product user with a malicious **username** created a KB version with a payload **version string** and **notes**.
- **Opened by** compliance and admin (scenario list, scenario dialog, KB list, KB dialog, users and teams), and by the malicious user themself (sidebar shell).

| Check, every screen | Fixed `esc()` |
|---|---|
| Injected `on*` or `autofocus` attributes in the parsed DOM | **none** |
| Unexpected elements (`<img>` from `"><img onerror>`) | **none** |
| JavaScript executed (`window.__pwned`, `alert`) | **none** |
| CSP violations | **none** (the payload never reaches script, so CSP isn't exercised) |
| Field values and attributes equal the exact stored text | **yes** (title, learning goal, notes, `data-kbver`, author `title`, user-card `title`) |
| Visible text shows `"`, `'`, `&`, `<`, `>` literally, never `&quot;` or `&amp;` | **yes** |

**Control with the old `esc()`:** Chrome parsed `autofocus=""` and `onfocus="window.__pwned=1 …"` on `#s-title` (the field was disabled for compliance, so the handler didn't fire). This confirms the check detects the bug.

The Phase 4A browser journey (40 page states, all roles) was re-run on the fix: 0 CSP violations, 0 overflow, no unexpected errors.

## Regression

| Run | Result |
|---|---|
| `pytest` | 445 passed (432 → 445) |
| `pytest tests` | 445 passed |
| `tests/test_security_html_escaping.py` alone | 13 passed |
| `tests/test_phase4a.py` alone | 24 passed |
| hotfix first, all files reversed | 445 passed |

No paid providers, no production credentials.

## Remaining dynamic-HTML risks
- **Pattern risk, not a current bug:** the frontend still builds HTML with template strings plus `innerHTML`, so safety depends on every interpolation being escaped. The new attribute guard test enforces this for attributes. Text-context interpolations are covered by the existing practice of passing data through `esc()`; no automatic guard exists for those.
- **`encodeURIComponent` doesn't encode `'`.** That's safe in today's double-quoted `href`s; a single-quoted attribute would need `esc(encodeURIComponent(…))`.
- **Production is still exposed until deployed:** it runs pre-Phase-1 code with the old `esc()` and no CSP. **Deploy this fix with the next release** (see the deployment gate in `PILOT_FOUNDATION_REVIEW.md`).

## Changes summary

| Area | Changed |
|---|---|
| Files | `static/app.js` (`esc()` only), `tests/test_security_html_escaping.py` (new), this document, a one-line plan note |
| Backend application logic | No |
| Stored data encoding | No |
| CSP | Unchanged (`script-src 'self'; style-src 'self'`) |
