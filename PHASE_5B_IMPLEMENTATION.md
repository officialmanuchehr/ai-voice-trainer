# Phase 5B — Manager Overview, My Progress, History

**Date:** 2026-10-05 · **Base:** `1169420` (version-binding fix) · **Plan item:** A1-4 · **Status:** implemented, **uncommitted**, not pushed or deployed.

## Scope
- **Overview** (`/overview`): the manager's landing page after login.
- **My Progress** (`/progress`): the manager's own results over time.
- **History** (`/history`): every one of the user's sessions with status, result and actions. It replaces the history panel on the training page.
- **Backend:** one read-only endpoint, `GET /me/progress`, plus three static page routes. No schema change, no new tables, no AI calls, no caching or jobs.

Not in scope: team analytics, benchmarks, targets, rankings, streaks, readiness scores, adaptive recommendations, and Phase 6.

## Data inventory
| Need | Source |
|---|---|
| Session list, status, title, product, difficulty, version | `/me/sessions` (`session_rows`), title, product and difficulty from the **bound** scenario version (fix `1169420`) |
| Final score, critical errors, disputed | `Score` row (stored; never recomputed) |
| Criteria | `Score.breakdown` (`score`, `max` per criterion) |
| Claim verdicts | `Score.claim_checks`, mapped through `fail_closed_verdict` |
| Next skill | `Score.feedback.next_skill` (evaluator output already stored) |
| Repeatability | `scenario_available` (current published state) |

## `GET /me/progress`
- **Caller only:** the user comes from the session cookie. The endpoint takes no parameters, so query strings such as `user_id`, `manager_id`, `username` or `team_id` are ignored (tested).
- **Roles:** the trainee roles (manager, sales_lead, training, admin) get 200; product and compliance get 403. Only managers see it in the navigation.
- **Response:** counts and aggregates only. It never contains transcripts, quotes, claim texts, explanations, the raw breakdown, hidden client fields or prompts (tested).

### Metric definitions (backend, `app/analytics.py::build_progress`)
- **Included sessions:** `status == "finished"` with a stored `Score`. Active, scoring and failed sessions are excluded from the metrics but counted in `sessions.in_progress / scoring / scoring_failed`.
- **Ordering:** `(started_at, id)` ascending.
- **Score:** the stored final `total`. A capped result stays 60.
- **Average:** arithmetic mean of the totals, rounded to 1 decimal.
- **First and latest:** the first and last included sessions in that order. `latest_at` is the session's `started_at`.
- **Trend:** one point per included session, chronological. No interpolation, smoothing or target line.
- **Criteria:**
  - per session, `clamp(score, 0, max) / max` (the first entry for each criterion);
  - per criterion, the mean of those ratios, `avg_pct` rounded to an integer, with `samples`;
  - sorted weakest first;
  - weakest and strongest are chosen on the unrounded mean, with ties going to the criterion earlier in the rubric;
  - `strongest` is null when there are fewer than 2 criteria.
- **Products:** grouped by the bound version's `product_id`, giving `sessions`, `avg_score` (1 decimal) and `sessions_with_critical_errors`, sorted by average, lowest first.
- **Compliance:** total critical errors, sessions with critical errors, and claim counts `approved / unapproved / forbidden` through the canonical fail-closed verdict.
- **`next_skill`:** `{source: "evaluator_feedback", text, session_id, started_at}` from the latest included session with a non-empty value, otherwise null.
- **Empty user:** a valid response with zero counts, null summary and empty lists.

## Frontend (presentation only)
- **No analytics math in JavaScript.** The pages print backend values. A static test fails if a page script uses `reduce`, `sort`, `Math.round`, sums, or subtracts first from latest.
- **Overview:**
  - KPIs: scored count, average, latest result with date, and sessions with critical errors;
  - a "first → latest" line;
  - a note on excluded sessions;
  - "Что потренировать": `next_skill` labelled "Совет из оценки тренировки от DATE", linked to that review, plus the weakest criterion;
  - the last 5 sessions and "Вся история";
  - CTA "Начать тренировку".
  - **New manager:** an onboarding state with "Начать первую тренировку".
- **My Progress:**
  - a scope note: only scored sessions count, the score is the stored score including the 60 cap, and excluded counts are shown;
  - KPIs;
  - an SVG trend with `role="img"` and an `aria-label` listing the values, a `<title>` per point, and a `<details>` table equivalent;
  - criteria bars (CSSOM widths from `data-pct`) with text badges "слабее всего" and "сильнее всего";
  - a products table;
  - compliance counts with explanations;
  - an empty state.
- **History:**
  - a table showing date, scenario (product · difficulty), status as a text badge, and score with the badges "критичная ошибка" and "оспорено";
  - actions: "Разбор" (or "Открыть" if not scored) to `/session?id=`, and "Повторить" to `/?repeat=<scenario_id>`, which opens the Phase 5A briefing; when the scenario is no longer published, "сценарий недоступен";
  - below 640px, rows become labelled cards so the actions stay reachable.
- **Navigation:**
  - manager: Обзор, Тренировка, Мой прогресс, История;
  - other trainee roles: История (`/history`, formerly `/#history`);
  - `/me/progress` is allowed but hidden for leads, training and admin;
  - managers land on `/overview` after login, other roles are unchanged.
- **Escaping:** every interpolated value goes through `esc()`, including numbers in SVG attributes. No new `KNOWN_SAFE` entries.
- **CSP:** unchanged and strict. No CDN, framework or build step.

## Active-session reload (documented limitation, unchanged)
- Reloading during a live session leaves it stored as `active`. It cannot be resumed.
- Overview and History show it as "в процессе", and History explains that it can't be continued and suggests "Повторить".
- Starting a new training creates a new session. Nothing is destroyed, and the active session is excluded from the metrics but counted.

## Tests
- **`tests/test_phase5b_progress.py` (21):** empty, one, several sessions, capped score, exclusions, normalisation, per-session mean, ties, single criterion, products after republish, compliance counts, `next_skill` latest and missing, privacy and parameters, roles, no private data.
- **`tests/test_phase5b_frontend.py` (16):** routes and scripts, which endpoints each page calls, no analytics math, the repeat link, `next_skill` wording, chart text equivalent and no target line, status as text, the training page no longer loading history, manager landing, and anonymous access getting no data.
- **`tests/test_phase4a.py`:** manager nav keys, shell pages, and active keys now also read from `initPage('…')`.
- **Results:**
  - full suite **522 passed**;
  - the full suite in reverse file order: **522 passed**;
  - escaping and frontend checks pass without Node (the Node check is skipped).

## Real-browser review (Chrome headless, stub providers, scratchpad only)
- **Data:** a new manager (`manager2`, empty), and an experienced `manager1` with 4 scored sessions across 2 products. They include a capped 60 with a critical error and an unsupported claim, a repeated scenario, 1 active session and 1 failed scoring. The second product and scenario were published through the real content workflow.
- **28 checks passed**, with no CSP violations, JS errors, hidden values, raw provider errors, "undefined", "NaN" or "null" on screen, and no horizontal overflow. Covered:
  - manager landing and nav order and state;
  - the empty states;
  - backend values shown;
  - `next_skill` wording;
  - one trend point per scored session;
  - bar widths;
  - table equivalent;
  - statuses and badges;
  - history to result (60 shown) and back;
  - "Повторить" opening the briefing;
  - dark mode, 390px light and dark;
  - keyboard order (skip link, nav, row actions) and visible focus.
- **Fixed during review:**
  - the chart's axis text was scaled too large, now fixed by sizing the viewBox to the container;
  - a cramped products table, now stacked;
  - History actions hidden off-screen on phones, now labelled cards.

## Known limitations
- Metrics are all-time; there are no time windows.
- `next_skill` is the evaluator's free text from one session, not an adaptive plan.
- Averages are computed per request in Python. This is fine at pilot volume; see A2-8.
- Active sessions cannot be resumed (above).
