# Phase 6 — Sales Lead / management experience

**Date:** 2026-10-06 · **Base:** `8ae0bc4` (Phase 5B) · **Status:** implemented, **uncommitted**, not pushed or deployed. Built under the four approved audit decisions.

## Scope
- **Обзор** (`/dashboard`): the team overview, revised. It is still shared with the training, product, compliance and admin roles.
- **Команда** (`/team`): new. Team managers with factual indicators.
- **Manager drill-down** (`/manager?id=`): new. One manager's progress and sessions.
- **Backend:** a narrower lead scope (Decision 1), factual indicators (Decision 2), `GET /dashboard/managers/{id}/progress` (Decision 3), one shared criterion rule (Decision 4), and a `recent_sessions` list in `/dashboard/data` (see below).
- **Unchanged:** schema, scoring, stored scores, session lifecycle. No AI calls, caches or jobs.

## Data inventory (what a sales lead can access)
| Endpoint | Scope for a sales lead |
|---|---|
| `GET /dashboard/data` | The lead's **current** team only; `team_id` is ignored. Aggregates cover active users with the `manager` role. Includes names. |
| `GET /dashboard/managers/{id}/sessions` | Only `role == manager` **and** the same team (`lead_may_view`). |
| `GET /dashboard/managers/{id}/progress` (new) | Same rule. |
| `/sessions/{id}/score`, `/transcript` (read only) | Only when the owner has `role == manager` on the lead's team. |
| `/me/progress`, `/me/sessions` | The lead's own training. It is never mixed into team numbers. |

Lead write access is unchanged: none, except on their own sessions.

## Authorization model (Decision 1)
- **One rule:** `app/security.py::lead_may_view(lead, target)` returns true only when the target exists, the lead has a team, `target.role == "manager"`, and the target's `team_id` equals the lead's.
- **Where it applies:**
  - session reads (`_load_session`: score, transcript, result);
  - the manager drill-down (`/sessions`);
  - the new `/progress`.
- **Before:** same-team membership alone was enough, so a lead could open another same-team lead's sessions, or a trainer's or admin's, including transcripts.
- **Unchanged:**
  - owner access;
  - admin (any session, any drill-down);
  - cross-team denial;
  - aggregate-only roles (training, product, compliance get 403 on drill-downs and individual sessions);
  - unknown ids return 404 (project convention, ids are random).
- **Team movement (accepted for the pilot, marked for Pilot QA / bank policy review):** authorization follows the user's **current** team. If a manager moves teams, the new lead sees all of their past sessions and the old lead loses access. Sessions do not record historical team membership. No schema change was made.

## Transcript privacy
- **Who can read individual transcripts:** the same as before for the owner and admin. A lead can read them for managers on their team (existing policy) and no longer for anyone else.
- **Overview, Team and drill-down progress data:** never include transcripts, quotes, claim texts, hidden scenario fields, prompts or provider output (tested with sentinels).
- **Drill-down session list:** the existing `session_rows` shape: title, product, difficulty, status, score, flags.

## Metric definitions (backend; JS only displays)
Common rules:
- **Scored session:** `status == "finished"` with a stored `Score`. Same rule as 5B. `/dashboard/data` previously counted any session with a `Score`.
- **Score:** the stored final total. A capped 60 stays 60.
- **Averages:** 1 decimal. Percentages: whole numbers.
- **Period:** `/dashboard/data` and Team use the selected period (7, 30, 90 days, or all, by `started_at`). The drill-down is all-time, and the page says so.
- **In scope:** active `manager` users on the lead's team. The lead's own and other non-managers' sessions are excluded.

**KPIs** (`kpi`):
- `managers_trained`: managers with at least 1 scored session;
- `total_managers`;
- `sessions_started`;
- `sessions_scored`;
- `avg_score`;
- `critical_errors`: total count;
- `sessions_with_critical_errors`.

Leads see 4 cards: managers trained (of total), scored (of started), average final score, and sessions with critical errors (of scored, with the total count of errors). Other roles keep their operational cards, such as AI latency and dispute rate.

**Per manager** (`managers`, sorted alphabetically by `full_name`, then id):
- `sessions` started, `scored`, `avg_score`, `first_score`, `last_score`;
- `last_session_at`: latest scored;
- `last_activity_at`: latest session of any status;
- `critical_errors`, `sessions_with_critical_errors`, `latest_has_critical_error`;
- `weakest_skill {criterion_id, name, avg_pct}`.

There is no classification, threshold or rank. `needs_help`, `reasons` and `critical_rate` were removed from manager rows.

**Team skills** (`skills`, `weakest_skill`): the shared criterion rule over the team's scored sessions. The page shows "Самый низкий средний результат среди критериев: X — Y%" as an observation. `recommendations` was removed: it was threshold-based (< 60%) plus heuristics.

**Shared criterion rule** (`summarize_criteria`, Decision 4), used by `/me/progress`, the drill-down, team skills and every manager row:
- per scored session, `clamp(score, 0, max) / max`, taking the first entry per criterion;
- per criterion, the mean over sessions;
- sorted weakest first on the unrounded mean, with ties going to the earlier rubric criterion.

Previously, manager rows didn't clamp and ties fell to dict order.

**Products** (`products`):
- product identity comes from the session's **bound** scenario version;
- fields: `sessions`, `scored`, `avg_score`, `critical_rate` and `sessions_with_critical_errors` (new);
- the UI shows "N (x%)" and no ⚠ ≥ 30% flag.

**Compliance** (`risks`):
- critical-error counts by evaluator type;
- claim verdicts `approved / unapproved / forbidden`, stored fail-closed at scoring;
- no derived risk score, and low scores are never treated as compliance findings.

**Trend:** the existing average final score per calendar week (Monday start), without empty weeks. The "порог 60" reference line was removed; 60 is the cap, not a target. The chart has a text label and a table.

**Recent activity** (`recent_sessions`, named views only): the 10 newest in-scope sessions of any status in the period, using the bound version's title, product and difficulty from `session_rows`, plus `user_id` and `full_name`.

> **Backend scope note:** `recent_sessions` is a small read-only addition to the existing `/dashboard/data` response (no new endpoint). It reuses `session_rows` and the same team scoping.

## Version binding
All new aggregation paths read product and difficulty through `bound_scenario` (session → bound `ScenarioVersion`). Tested after a republish to another product and difficulty: team products, recent activity, and the drill-down.

## Manager drill-down
- **Data:** `/dashboard/managers/{id}/progress` returns `{user: {id, full_name}, ...build_progress}`, unchanged from 5B (tested equal to the manager's own `/me/progress`). It also uses `/dashboard/managers/{id}/sessions`.
- **Rendering:** the 5B progress layout through the shared `static/js/progress-view.js`: trend with table, criteria, products, compliance. Then:
  - the evaluator's advice, labelled with its source session;
  - the session list with "Разбор" or "Открыть" (read only).
- **No actions on the manager's behalf:** no repeat and no dispute.

## Navigation and landing
- **Sales lead:** Обзор (`/dashboard`), Команда (`/team`), Тренировка, История (their own training). Leads now land on `/dashboard` after login.
- **Admin:** may open `/team` (hidden). Other roles are unchanged.

## Empty states
- team without managers;
- manager without training ("нет тренировок", or "Тренировок пока нет" in the drill-down);
- training without scored sessions ("нет оценённых", plus a scope note);
- no activity in the period;
- failed scoring and active sessions are shown as statuses and not counted as scored;
- no critical errors in the period.

## Accessibility and responsive
- **Text first:** status badges always carry text; critical indicators read "критичная ошибка", "N в M трен." and "в последней".
- **Charts:** have `role="img"` labels and table equivalents.
- **Tables:** have captions and `scope="col"` headers. Manager names are links, reachable by keyboard (tested).
- **Narrow screens:** below 640px, Team, recent activity and drill-down tables become labelled cards. No horizontal overflow at 390px in light or dark mode.

## Tests
- **`tests/test_phase6_lead.py` (31):**
  - the privacy matrix: Lead A reaches Manager A's drill-down, score and transcript, but gets 403 on Manager B, same-team lead, training, product, compliance and admin sessions or drill-downs;
  - admin and owner access unchanged; other roles 403; unknown 404;
  - team data free of out-of-scope users and sessions, even with `team_id`;
  - alphabetical facts with no classification fields;
  - active and failed sessions counted but not scored;
  - clamped criteria with rubric ties; team skills normalised and matching the drill-down;
  - drill-down equal to `/me/progress`; no transcript or hidden fields;
  - bound products after republish; critical and claim counts; empty team; untrained manager.
- **`tests/test_phase6_frontend.py` (13):**
  - routes; each page calls only scoped endpoints;
  - no analytics math, ranking words or thresholds in JS; no reference line or recommendations;
  - alphabetical explanation; lead nav; read-only drill-down links.
- **Updated:**
  - `test_phase4a.py`: new shell pages, the shared view module, and a `{manager1}` probe placeholder;
  - `test_phase5b_frontend.py`: chart checks now read `progress-view.js`; lead landing.
- **Results:** **570 passed** (baseline 522), and 570 in reverse file order. Escaping and frontend checks pass without Node.

## Browser verification (Chrome headless, stub providers, scratchpad only)
- **Data:**
  - Team A (`lead1`): managers with 2 products, a capped 60 with a critical error and an unapproved claim, a forbidden claim, an active session, a failed scoring, and untrained managers;
  - also a second same-team lead and a same-team trainer, each with private sessions;
  - Team B: its own lead and manager.
- **Result:** 23 checks passed. No out-of-scope names or sentinels anywhere for Lead A, no hidden values, raw errors, "undefined" or "NaN", ⚠ flags, CSP violations, JS errors or overflow. Covered:
  - landing, nav, overview sentences, the forbidden-claim count;
  - alphabetical team, factual empty rows;
  - drill-down: title, 3 trend points, second product, open result;
  - direct URLs for Team B's manager, the same-team lead, the trainer, and their sessions all refused;
  - Team B's lead sees only Team B;
  - dark mode, 390px, keyboard.
- **Fixed during the review:** the overview's products table was clipped at half width; it is now full width.

## Known limitations
- Team scope follows the **current** team (above). This needs bank policy review.
- The overview trend groups by calendar week (existing). The drill-down is all-time, not period-filtered.
- Team aggregates cover **active** managers. Deactivated managers' sessions drop out of team numbers but remain reachable by drill-down URL for their lead.
- Without a team filter, the admin and aggregate-role dashboard counts every user's sessions, including leads' and trainers' (existing behaviour, not part of the lead view).
- A refused session page still shows an empty "Транскрипт" card under the error (cosmetic, existing).
- The team table isn't sortable (alphabetical by decision). Active sessions can't be resumed (5B limitation, unchanged).
