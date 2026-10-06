# Phase 8 — Compliance, admin and pilot polish

**Date:** 2026-10-06 · **Base:** `64a99bc` (Phase 7) · **Status:** implemented, **uncommitted**, not pushed or deployed. Last feature phase before Phase 9 (Pilot QA and launch readiness).

## Audit — gap inventory
No STOP condition applied:
- no transcript-access broadening;
- no score changes;
- no four-eyes rule invented;
- no identity, SSO, team-history or infrastructure work needed;
- no new P0 defect found.

| # | Finding | Class | Phase 8 |
|---|---|---|---|
| 1 | Org-wide dashboard (admin without a team filter, and training/product/compliance) counted **every role's** practice sessions, not just managers' | P1 | Fixed: management analytics count `role == manager` sessions only |
| 2 | Product and compliance users landed on the training page, which they cannot use | P1 | Fixed: they land on the new work queue |
| 3 | No work queue for content roles (A1-6) | P1 | Built over `can_transition` |
| 4 | Audit view: raw JSON details, only a type filter, and session links shown to compliance that lead to 403 | P1 | Readable details; action, actor and type filters; links only where the role may open them |
| 5 | `user.edit` audit stored only new values (A2-1, first part) | P1 | Now `{from, to}` |
| 6 | Users: no search or filters; deactivate, role, team and password changes saved without confirmation (A1-8) | P1 | Search, role/team/status filters, confirmation listing every consequential change |
| 7 | Refused session page rendered an empty "Транскрипт" card | P1 | Fixed: one clear "Разбор недоступен" state; the transcript panel appears only with data |
| 8 | Archiving the published KB didn't say which live scenarios it affects (A1-6) | P1 | The confirmation lists the published scenarios of that product |
| 9 | Disputes have no status, reviewer or resolution field; compliance can't see disputes or transcripts (A1-5) | Bank decision B-2, then a P1 schema task | Not built. Leads (own team, named, with link), admin (all) and training (no names, no link) see disputes as before |
| 10 | Teams: create only; no rename, deactivate or lead assignment | P2 | Unchanged; the list shows member counts and filters users by team |
| 11 | Compliance sees per-manager `session.scored` events (actor, total, critical-error types) in the audit log, while the dashboard is aggregate-only for that role | Bank decision | Existing, deliberate PRD §14 journal access; recorded for review |
| 12 | Other A2-1 events (`session.finish`, `scoring.failed`, `auth.logout`, `team.edit`) | P2 | Not added |

## What was built
- **Work queue (`/queue`, nav "Задачи"; training, product, compliance, admin):**
  - backed by `GET /admin/queue`, which lists versions where `can_transition` allows the caller **approve** or **publish**;
  - plus KB drafts with review blockers the caller may edit;
  - each item shows whether an existing guard currently blocks it: `kb_unreviewed` with the exact entries, `no_published_kb`, `kb_not_clean`;
  - archive and "back to draft" are not presented as work;
  - no status, owner or quorum is added;
  - every item links straight into the Phase 7 editor (`/admin?tab=…&open=…&v=…`; no duplicate editor);
  - compliance and admin also see the last content changes from the audit log.
- **C-9:** the published merchant KB 1.0.0 has no pending step, so it is **not** queue work, and nothing is special-cased (tested: no `obj_taxes` or `merchant_onboarding` in any frontend code). It surfaces in the queue only when a corrective draft with `needs_review` exists, through the generic mechanism. C-9 remains **open**.
- **Audit:**
  - filters: type, action, actor (partial match) and object id on the server;
  - readable details: transitions, versions, titles, scores, error types, role/team/status `from → to`, "пароль изменён", IP;
  - links to content editors for everyone with audit access; session links for admin only;
  - empty state.
  - Passwords, transcripts and content bodies were never stored in audit and still aren't (tested with a sentinel password).
- **Users and teams (admin):**
  - search by login or name; filters by role, team (including "Без команды") and status; "показано N из M"; empty state;
  - editing access, role, team or password opens a confirmation naming the user and each change, including that a team change moves the manager's visible history to the new lead;
  - a name change alone saves directly;
  - the password is set by the admin and never shown again;
  - the team list shows member counts and the current-team rule.
  - Existing guards are unchanged: admin can't deactivate themselves or drop their own admin role; deactivated users can't log in; no self-registration route.
- **Analytics scope:** org-wide numbers now cover managers only. Team scope is unchanged from Phase 6.
- **Session page:** a refused or missing session shows one clear state and never an empty transcript container, and it doesn't reveal whether content exists (403 and 404 read the same).
- **Landing:** product and compliance → `/queue`; manager → `/overview`; lead → `/dashboard`; training and admin unchanged (`/`).

## Behaviour documented, not changed
- **Deactivated managers:**
  - **team view (lead, or admin with a team):** roster **and** team numbers cover active managers only, so a deactivated manager's past sessions drop out of team numbers;
  - **org-wide view:** they still count;
  - **nothing is deleted:** the lead can still open that history by drill-down URL, because the manager keeps their team.
  - Whether team numbers should keep departed managers is a **bank policy decision** (recorded below); there is no schema change.
- **Team movement:** history follows the **current** team (Phase 6). Bank policy decision.
- **Disputes:**
  - a dispute is an audited note (`score.dispute`); the score is never changed (tested);
  - only the owner can dispute;
  - **no status or resolution exists in the data model**, so a review workflow needs B-2 (who reviews) and then a small additive schema change.

## Backend changes
- `analytics.build_dashboard`: org-wide sessions restricted to manager-role users.
- `GET /admin/queue` (read-only, content roles).
- `GET /admin/audit`: optional `action`, `actor` and `entity_id` filters.
- `user.edit` audit details: `{from, to}`.
- Page route `/queue`.
- Unchanged: schema, RBAC, transcript access, lifecycle.

## Navigation (verified in Chrome)
| Role | Navigation |
|---|---|
| Manager | Обзор, Тренировка, Мой прогресс, История |
| Lead | Обзор, Команда, Тренировка, История |
| Training | Обзор, Тренировка, История, **Задачи**, Сценарии, База знаний |
| Product | Обзор, **Задачи**, Сценарии, База знаний |
| Compliance | Обзор, **Задачи**, Сценарии, База знаний, Журнал действий |
| Admin | Обзор, Тренировка, История, **Задачи**, Сценарии, База знаний, Пользователи и команды, Журнал действий |

## Tests
- **`tests/test_phase8.py` (36):**
  - **Queue:** steps per role equal the lifecycle; blocked guards; KB editors see their blockers; access by role; metadata only; C-9 not special-cased; no hard-coded content.
  - **Audit:** filters; `from → to` without password; access by role.
  - **Analytics and deactivation:** org analytics count managers only; deactivated-manager behaviour as documented.
  - **Disputes:** no score change; own lead only; compliance and training see no transcript; owner-only dispute.
  - **Users:** admin-only user and team APIs; no self-registration; admin lock-out guard; deactivated login refused.
  - **Frontend contracts:** queue endpoints, user confirmations and audit link rules, refused-session state, landing.
- **Updated:** `test_phase4a.py` (shell pages), `test_phase5b_frontend.py` (landing map).
- **Results:** **664 passed** (baseline 626), also in reverse file order. Without Node, the static checks pass and the Node checks are skipped.

## Browser verification (Chrome headless, stub data, scratchpad only)
All six roles logged in and **every nav destination** was opened and checked: no XSS or injected elements (malicious strings in a dispute comment and a user name), no CSP violations, native dialogs, JS errors, error states, "undefined", "NaN" or "null", and no overflow. The 20 targeted checks passed:
- landing per role;
- compliance: queue with exact KB blockers and the scope note; deep link into the editor; audit with no session links; action filter; refused session shows a clear state with no transcript card; no dispute comments;
- lead: own-team dispute;
- admin: search; the deactivate plus role-change confirmation names the user and changes and focuses "Отмена"; Escape cancels; confirming applies; inactive filter; empty filter state; audit `статус: активен → отключён`, `роль: … → …`; session link for admin;
- training: can't open the audit or users tabs by URL;
- dark mode and 390px for queue, users and audit;
- keyboard: skip link first, search.

## Bank decision register (open; not solved here)
| Id | Decision |
|---|---|
| B-1 / B-2 | Four-eyes rules; who approves what; **who reviews disputes** (compliance and/or training), and whether compliance may open disputed sessions |
| B-3 / B-4 | External AI provider approval (Anthropic, Deepgram, ElevenLabs; DeepSeek dialog model) |
| B-5 | Allowed data and processing regions (Neon US-East today) |
| B-6 | Hosting model |
| B-7 | SSO / IdP |
| B-8 | User provisioning ownership |
| B-9 | Transcript, score and audit retention; deletion and export |
| B-10 | Pen-test requirements |
| B-11 | Network restrictions |
| B-12 | Log export / SIEM |
| B-13 | Production security requirements (password policy, session TTL, MFA) |
| B-14 | Basic Auth outer gate during the pilot |
| B-15 | **Historical team membership:** should a lead see a moved manager's past sessions; should team numbers keep deactivated managers |
| B-16 | **Audit visibility:** compliance sees per-manager score events in the journal; confirm this is intended |

**Bank content:**
- C-1…C-6: approved facts for РКО, Эквайринг, Зарплатный проект, Кредит, plus compliance restrictions;
- C-3: Эквайринг terminology (`merchant_onboarding`);
- C-7: approval of the 11 draft scenarios;
- C-8: duration hints and success metrics;
- **C-9:** `obj_taxes` tax statement in the published merchant KB.

None of these is complete without bank confirmation.

## Readiness classification
| Class | Items |
|---|---|
| **Engineering P0** | None known |
| **Engineering P1** | A2-2 input limits (text length, audio size, per-user turn rate); A2-4 persona-break guard line in the client prompt; A2-6 CI on push; A2-11 remove production DB credentials from local `.env.local` (process); dispute review status and reviewer note (additive schema) **once B-2 is decided** |
| **Bank decision** | B-1…B-16 above |
| **Bank content** | C-1…C-9 |
| **Pilot QA (Phase 9)** | Real-provider gate run (paid; needs approval); end-to-end voice latency on Vercel; microphone and audio on bank devices and browsers; STT quality for Russian/Tajik speech; deployment checklist incl. `init_db` and env; backup/restore drill; the active-session reload limitation (5B) checked against pilot expectations; full six-role walkthrough on the deployed build |
| **Post-pilot** | A1-10 sortable/filterable team table; A1-11 duration hints (after C-8); A1-12 per-stage latency on the dashboard; A2-1 remaining audit events; A2-3 token revocation; A2-5 unique turn index; A2-7 Alembic; A2-8 SQL aggregation; A2-9 cleanup; A2-10 vocabulary config; team rename/deactivate; diff vs the live version; A3-* |

## Known limitations
- No dispute status or resolution (data model); compliance has no dispute access (B-2).
- The queue shows the latest state per version; it is a view, not a task assignment.
- The audit list returns up to 300 rows per filter (no paging).
- Team administration is create-only.
