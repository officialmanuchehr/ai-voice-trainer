# Phase 4A — Design system and shared app shell: implementation record

**Date:** 2026-10-05 · **Base:** docs checkpoint `cdb8ea8` (after Phase 3B `fbda337`) · **Scope:** visual foundation, app shell and role-aware navigation, existing pages moved into the shell, CSP exit. No feature redesign.
**Git:** uncommitted, for review. Nothing pushed, merged or deployed.

## 1. Frontend architecture

**Before:**
- 5 HTML pages, each with one large inline `<script>` (about 900 lines in total);
- 43 inline `style=""` attributes, plus more inside JS templates;
- one `static/app.css`;
- a top-bar header built by `initPage()` in `static/app.js`;
- the CSP needed `'unsafe-inline'` for scripts and styles.

**After (still framework-free; no npm, bundler or build step; no new dependency):**
```
static/
  css/app.css            design tokens + base + shell + components + utilities (one stylesheet)
  app.js                 shared core (unchanged role): api(), esc(), fmtDate(), renderResult()…
  theme.js               theme switcher (unchanged, loaded in <head>)
  favicon.svg            product mark
  js/ui.js               toast(), stateHtml(), setLoading()
  js/shell.js            sidebar, header, role-aware nav, mobile drawer, initPage()
  js/nav.json            navigation config (data; checked against the backend by tests)
  js/pages/training.js   ← moved from index.html
  js/pages/session.js    ← moved from session.html
  js/pages/dashboard.js  ← moved from dashboard.html
  js/pages/admin.js      ← moved from admin.html
  js/pages/login.js      ← moved from login.html
  index.html, session.html, dashboard.html, admin.html, login.html   (markup only)
```
- **Classic scripts, not modules.** Each page loads, in order, `theme.js` (head) → `app.js` → `ui.js` → `shell.js` → `pages/<page>.js`, as plain `<script src>` at the end of `<body>`. The existing code shares globals (`api`, `esc`, `renderResult`), so classic scripts kept every page script working unchanged. ES modules would have meant rewriting those dependencies, with no benefit for the pilot.
- **Page scripts moved verbatim.** The only edits were targeted:
  - inline styles → classes;
  - link-buttons → `<button>`;
  - `alert()` → toast;
  - shell header and active-nav calls;
  - the `javascript:history.back()` link → button.
- **Logic unchanged.** Business logic, API calls and the Phase 3A transcript reconciliation are as before.

## 2. Design tokens (`static/css/app.css`, CSS variables)

| Group | Tokens |
|---|---|
| Surfaces | `--color-bg`, `--color-surface`, `--color-surface-muted`, `--color-sidebar`, `--color-hover`, `--color-selected` |
| Text | `--color-text`, `--color-text-secondary`, `--color-text-tertiary`, `--color-text-inverse` |
| Lines | `--color-border`, `--color-border-strong` |
| Brand | `--color-accent` (trust blue `#1d5bb8`), `--color-accent-hover`, `--color-accent-soft`, `--color-focus` |
| Semantic | `success`, `warning`, `danger`, `info`, `neutral`, each with a `-bg` tint |
| Data viz | `--color-series-1`, `--color-track`, `--color-client` |
| Typography | system font stack (no web-font download); sizes 12/13/14/16/18/22 + KPI 26; weights 500/600 |
| Spacing | 4 px scale `--space-1`…`--space-8` |
| Shape | radius 6/8/12/full; shadows sm/md/lg; `--focus-ring` |
| Layout | sidebar 248 px, header 64 px, content max 1200 px (narrow 860 px) |

Light and dark palettes cover system preference and an explicit choice; the existing theme switcher is kept. Contrast was computed for the main pairs:

| Pair | Contrast |
|---|---|
| Body text | 17.5:1 light, 14.3:1 dark |
| Primary button | 6.5:1 light, **6.6:1 dark** |
| Status text on its tint | 4.8–5.7:1 |
| Tertiary text | 4.5:1 light, 6.0:1 dark |

The **dark** primary button was 2.8:1 with white text, as found in the browser review. It now uses dark text on the light-blue accent.

## 3. Shared components

| Component | Implementation |
|---|---|
| Buttons | Primary (default `<button>`), `.secondary`, `.danger`, `.ghost`, `.small`, `.icon-button`, `.link` (a button styled as a link, for in-page actions), `:disabled`, `.is-loading` (spinner, via `setLoading()`) |
| Cards | `.panel` (content card), `.card` (catalogue item), `.kpi` (stat card), `.section-head` (card title + actions) |
| Badges | `.chip` / `.badge` with a dot marker **and** a text label (meaning never by colour alone): draft / approved / published / archived (outline), easy / medium / hard, topic, success / warning / error / info, `.role-badge` |
| Forms | `label.field` (label above control), inputs, selects, textarea, `.code` textarea, `.field-help`, `.field-error`, `.checkbox-row`, disabled and read-only styles, focus ring |
| Tables | Uppercase compact headers, row hover, numeric alignment, `.table-wrap` horizontal scroll on narrow screens, muted rows |
| Feedback | `toast()` (aria-live region, auto-dismiss except errors), `.alert` info / success / warning / error, `.error-box`, `.note-box`, `.critical-box`, `stateHtml('loading' / 'empty' / 'error')`, `.spinner` |
| Dialog | Native `<dialog>` (focus trap and Esc from the browser), `.dialog-head`, `.dialog-actions`, labelled by its title (`aria-labelledby="dlg-title"`), close button with `aria-label` |
| Shell | `.app-shell`, `.sidebar`, `.nav-group`, `.nav-link` (`aria-current="page"`), `.user-card`, `.app-header`, `.app-content`, `.page` |

Confirmation dialogs for dangerous actions aren't added in this phase: no existing workflow has one. They belong to A1-8 (admin, Phase 8).

## 4. App shell
- **Desktop layout:** a sticky left sidebar plus a main column with a sticky page header and the content area.
- **Sidebar:**
  - product mark and name ("AI Voice Trainer · Тренажёр продаж и комплаенса");
  - grouped navigation (Работа / Контент / Администрирование) with inline SVG icons (9 small paths, no icon library);
  - user card (initials, name, role, team, with a tooltip for long values);
  - theme switcher and logout.
- **Header:** page title, a short subtitle, and a right-hand action slot. The dashboard filters live there; the session page has "← Назад".
- **Built from:** `/auth/me` (the user's own record) and `/static/js/nav.json` only; no other data is fetched (tested).
- **Unauthorised page:** shows a "no access" state inside the shell (`requiredFlag`). The backend refuses the data regardless.

## 5. Role-aware navigation
Defined in `static/js/nav.json`. Only pages that exist are listed. IA items without a page yet are **not** shown, to avoid fake destinations: "My Progress", "Reports", "Training Programs", "Approvals", "Disputed Scores", "Products".

| Role | Sidebar |
|---|---|
| Manager | Тренировка · История |
| Sales lead | Обзор · Команда · Тренировка · История |
| Training | Обзор · Тренировка · История · Сценарии · База знаний |
| Product | Обзор · Сценарии · База знаний |
| Compliance | Обзор · Сценарии · База знаний · Журнал действий |
| Admin | Обзор · Тренировка · История · Сценарии · База знаний · Пользователи и команды · Журнал действий |

**How existing pages map:**
- "История" and "Команда" are anchors into the training and dashboard pages.
- Admin sections are `/admin?tab=…`; the old in-page tab bar is removed and replaced by the sidebar.
- Training keeps "База знаний" because the backend lets it read KB versions today (needed for authoring scenarios). The IA doesn't list it for that role; worth confirming as part of B-2.

**Backend agreement, tested:** every item names a `probe` endpoint. For each of the 6 roles, a visible item's probe returns 200 and a hidden item's returns 403. The one documented exception is "Команда" (`hidden_but_allowed: admin`): admins can open any team's drill-down but manage teams elsewhere. The nav is UX only; RBAC is unchanged.

## 6. Login
- **Visual refresh:** centred card with the product mark, "Вход" title, labelled fields, full-width primary button with a loading state, error area (`role="alert"`) and theme switcher.
- **Unchanged:** authentication, throttling (429 message shown as returned), cookies, the `next` redirect, Basic Auth. The browser check verified the wrong-password message and the throttle message in the real form.

## 7. Existing pages moved into the shell
All five pages: training (catalogue, history, live session, result), session review, dashboard, admin (4 sections and dialogs), login. Inside the pages only spacing, typography, buttons and states changed; workflows are unchanged (deep redesign is Phase 5+).

## 8. Accessibility (practical, not a certification)
- **Keyboard and focus:**
  - Skip link: first Tab focus, and Enter moves focus to `#main` (verified in Chrome for all roles).
  - Visible `:focus-visible` ring on every interactive element.
  - Native `<dialog>` with Esc, labelled by its title.
  - Mobile drawer button has `aria-controls` / `aria-expanded`; Esc closes the drawer.
- **Semantics:**
  - `<a href="#">` used as buttons → real `<button>`s (admin version links, dashboard manager names).
  - The `javascript:` back link → a button.
  - `aria-current="page"` on the active nav item.
- **Labels:** every filter and select has a label (visually hidden where the context is obvious).
- **Live regions:** `role="status"` / `role="alert"` on messages and toasts; the chat area is `aria-live="polite"`.
- **Status chips:** carry a text label; colour is never the only signal.
- **Reduced motion:** honoured for the drawer and spinners.

## 9. Responsive behaviour
- **Desktop first.** Below 1,024 px the sidebar becomes an off-canvas drawer (menu button in the header, backdrop, Esc).
- **Reflow:** grids collapse to one column below 640 px; tables scroll horizontally inside their card; chat bubbles widen.
- **Verified in Chrome at 390 × 844:** no horizontal page overflow on any page, and the drawer opens and closes.

## 10. CSP impact
- **Before (Phase 3B):** `script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'`.
- **After:** `script-src 'self'; style-src 'self'`. **`'unsafe-inline'` is fully removed.**
- **Why that's safe:** no inline `<script>`, `<style>`, `style=""`, `on…=` handlers or `javascript:` URLs remain in pages or JS templates (tested). Dynamic sizes (dashboard bars, tooltip position) use CSSOM (`el.style.x = …`), which `style-src 'self'` allows.
- **Change:** one constant in `app/http_security.py`. All other directives are unchanged; `/docs` and `/redoc` (development only) still skip the CSP.
- **Real-browser result:** Chrome with the strict CSP enforced showed **0 violations** across 40 page states, all 6 roles.

## 11. Tests
- **New `tests/test_phase4a.py` (24 tests):**
  - nav visibility = backend permission for all 6 roles (each probe called as each role);
  - every role has destinations and managers see no content tools;
  - nav targets exist;
  - pages only activate known nav keys;
  - every page's assets resolve with the correct content type (5 pages);
  - shell skeleton and script order on 4 pages;
  - login page standalone, with its form;
  - the old stylesheet is gone;
  - no inline styles, `eval`, `javascript:` or string timers in any frontend JS;
  - **every API path the frontend calls is a real route** (from the OpenAPI schema);
  - the shell uses only `/auth/me` fields;
  - the shell requests nothing beyond `/auth/me`, `nav.json` and logout.
- **Two existing tests adapted, not weakened:**
  - `test_phase3a::test_frontend_never_renders_raw_http_status` now checks the reconciliation code in `js/pages/training.js` and that the page loads it, instead of looking inside `index.html`.
  - `test_phase3b::test_csp_fits_the_existing_frontend` now asserts the **stricter** policy: no `'unsafe-inline'` or `'unsafe-eval'`, and no inline code in any page.

**Results:**
```
pytest                     432 passed   (408 → 432)
pytest tests               432 passed
each file alone            all green
4A first, reversed         432 passed
shuffled                   432 passed
```

## 12. Browser verification status
**Performed: yes, in real Google Chrome (headless)**, driven by Playwright from a scratchpad virtualenv. Playwright is **not** a project dependency; nothing was added to `requirements*.txt`. The server ran locally on the repo copy with stub providers and demo users.

| Check | Result |
|---|---|
| Login, all 6 roles, every sidebar destination, light theme 1440 × 900 | 40 page states, **0 CSP violations, 0 JS errors, 0 failed requests, 0 horizontal overflow** |
| Manager flow: start scenario → text turn → AI reply → finish → result | Works; result rendered (stub score) |
| Session review page and "← Назад" button | Works |
| Admin: scenario dialog opens, labelled by its title | Works |
| Dashboard with data: bar widths applied via CSSOM | Works (`30%`, `40%`, `47%`…) |
| First Tab → skip link → Enter → `#main` | Works (fresh loads, all roles) |
| 390 × 844: landing and training, drawer open | No overflow; `aria-expanded=true` |
| Dark theme login | Rendered; contrast issue found and fixed (§2) |
| Wrong password and throttle messages in the real form | Shown correctly |

**Screenshots reviewed visually**:
- Pages: login (light and dark), manager catalogue, active session and result, admin dialog, admin dashboard, narrow drawer.
- Issues found and fixed: toolbar `<select>` stretching to its longest option, the cramped sidebar footer, line height of name buttons, dark-mode button contrast, and the missing favicon (a 404).

**Not verified in a browser:**
- **Microphone recording and real TTS audio playback.** Headless Chrome has no microphone, and stub TTS returns empty audio. `Permissions-Policy: microphone=(self)` is unchanged from Phase 3B, and the mic code is unchanged.
- **Safari and Edge.**
- **Real-provider latency.**

These remain deployment-gate items 8–9.

## 13. Backend application logic changed
**No.** The only backend change is the CSP header constant in `app/http_security.py` (a tightening). Routes, RBAC, scoring, providers, prompts, schema, throttling, request IDs and error handling are untouched (`git diff -- app/` shows only that file).

## 14. Known limitations
- **Emoji in the mic button:** "🎤 / 🔴" and a few "⚠" markers remain inside existing page content. Replacing them belongs to the Phase 5 session redesign.
- **The admin KB "new version" flow still uses `prompt()`;** the structured editors replace it in Phase 7.
- **Some IA destinations aren't in the nav yet:** Reports, My Progress, Approvals, Disputed Scores, Training Programs, Products. They come with their phases, not as placeholders.
- **Light-mode tertiary text is exactly 4.5:1.** That's acceptable for metadata, but the margin is thin.
- **Full-page screenshots show the sticky sidebar and header** at their original position; this is a capture artifact, not a layout bug (live viewport verified).
- **Not run on real hardware:** Safari, Edge and microphone or audio checks (see §12).

## 15. Remaining Phase 4 / next UI work
- **Phase 5 (manager):** live training screen (states, timer, client identity, mic UI without emoji), results hierarchy, Overview / My Progress page (needs a read-only `/me/progress` endpoint).
- **Phase 6:** lead Team and Performance views, Reports.
- **Phase 7:** structured KB and scenario editors (replacing `prompt()` and raw JSON).
- **Phase 8:** compliance approvals queue and disputes (after B-2), admin users and teams with confirmation dialogs.
