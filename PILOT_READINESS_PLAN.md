# Pilot Readiness Plan — AI Voice Trainer (Bank Eskhata pilot)

**Date:** 2026-10-05 · **Source of truth:** `PILOT_READINESS_AUDIT.md` (commit `da4b55d`)
**Status:** plan for review. **Phase 1 implemented** (A0-1, A0-5, A1-0); see `PHASE_1_IMPLEMENTATION.md`. **Phase 1b implemented** (three bugs found at the start of Phase 2: duplicate scoring criteria, fail-open claim verdicts, draft products in `/products`); see `PHASE_1B_IMPLEMENTATION.md`. **Phase 2 test coverage complete** except the rows that depend on Phase 3 behaviour (login throttling, AI provider failures); see `PHASE_2_IMPLEMENTATION.md`. **Phase 3A implemented** (A0-3, A0-4: AI service failure handling); see `PHASE_3A_IMPLEMENTATION.md`. **Phase 3B implemented** (A0-6 login throttling, A1-9 docs off + security headers, plus request IDs, safe 500s, diagnostic redaction); see `PHASE_3B_IMPLEMENTATION.md`. **Phase 4A implemented** (A1-1 design system + app shell; CSP `'unsafe-inline'` removed); see `PHASE_4A_IMPLEMENTATION.md`. **Security hotfix:** `esc()` now escapes quotes (stored attribute injection); see `SECURITY_HOTFIX_HTML_ESCAPING.md`. **Phase 5A implemented** (A1-2 live training screen, A1-3 results; catalogue and briefing); see `PHASE_5A_IMPLEMENTATION.md`. **Fix:** historical analytics bound to the session's scenario version; see `FIX_HISTORICAL_ANALYTICS_BINDING.md`. **Phase 5B implemented** (A1-4 Manager Overview, My Progress, History and `GET /me/progress`); see `PHASE_5B_IMPLEMENTATION.md`. **Phase 6 implemented** (sales lead overview, team view and manager drill-down; lead access narrowed to managers of the lead's team; `needs_help` thresholds removed). A1-10 is only partly covered: the team table is alphabetical by decision, not sortable or filterable. See `PHASE_6_IMPLEMENTATION.md`. **Phase 7 implemented** (A1-7 structured scenario and KB editors; read-only JSON view; no diff vs the live version yet); see `PHASE_7_IMPLEMENTATION.md`. **Bank content blocker C-9:** the published `merchant_onboarding` KB 1.0.0 contains an unconfirmed tax statement (`obj_taxes`), so product content is not fully pilot-approved. **Phase 8 implemented** (work queue, audit filters and readable details, user search/filters/confirmations, org analytics limited to managers, refused-session state); see `PHASE_8_IMPLEMENTATION.md`, which also holds the consolidated bank-decision register and readiness classification. **Phase 9 (pilot QA)** done in engineering: A2-2 input limits, A2-4 persona guard, A2-6 CI, stub-provider startup warning, acceptance tests (730 passing). See `PHASE_9_LAUNCH_READINESS.md`, `PILOT_ACCEPTANCE_MATRIX.md`, `DEPLOYMENT_CHECKLIST.md`, `BANK_PILOT_DECISIONS.md`, `PILOT_CONTENT_GATE.md` and `PILOT_RUNBOOK.md`. **Pilot status: NO-GO today** (bank decisions, content, real-provider gate). Nothing else is implemented yet.

**Categories**
- **A — We can implement now:** technical/product work that needs no bank decision.
- **B — Requires a bank decision:** do not implement until confirmed.
- **C — Requires bank content:** never invented by engineering.

**Priorities (category A only)**
- **P0:** pilot would be unsafe, incorrect, insecure or unreliable without it.
- **P1:** needed for a professional pilot experience.
- **P2:** production hardening that can wait until the pilot core works.
- **P3:** future SaaS work, kept out of the pilot.

**Complexity:** S = one file or endpoint, minimal UI · M = several files, or a page plus endpoint plus tests · L = new subsystem or many pages. No day estimates are given: the main uncertainty is review cycles and bank content, not coding effort.

---

## 1. Work inventory

### A — We can implement now

#### P0 — Pilot blockers

| ID | Task | Audit ref | Size |
|---|---|---|---|
| **A0-1** ✅ | **Server-side guard against publishing unreviewed KB content.** Block `approved` and `published` for a KB version if any `approved_facts[]` (and, for consistency, `approved_arguments[]`, `objections[]`, `disclaimers[]`) has `needs_review: true`, or `draft_note` is present. Return 409 with the count and IDs of the unreviewed entries. Add the same guard to scenario publish: the product's KB must be published (already enforced) and clean. | P0-1 | S |
| **A0-2** ✅ | **Safety-net tests before any change:** scoring arithmetic, the 60 cap (both triggers), KB enforcement, scenario and KB version linkage, hidden-field exclusion, the AI client prompt containing only the bound KB version. See §8. | P1-11 | M |
| **A0-3** ✅ | **Transcript ↔ screen consistency on provider failure.** Today a failed text turn leaves the manager's bubble on screen although it was rolled back. A voice turn that fails at TTS has already committed both turns, which the UI never shows, so a retry duplicates them. Rule: the screen must always equal the stored transcript. | P1-1 | M |
| **A0-4** ✅ | **No raw provider or exception text shown to users.** `finish_error` stores `str(exc)` and `/score` returns it to the manager. Provider HTTP errors become unhandled 500s. Map them to stable error codes plus Russian messages; keep the technical detail in server logs only. | P1-1, Security §6.9 | S |
| **A0-5** ✅ | **The score cap is always explained.** When the cap is triggered by a claim verdict without a matching `critical_errors` entry, return an explicit `cap_reason` (which claims triggered it) and render it. | P1-2 | S |
| **A0-6** ✅ | **Login throttling plus failed-login audit.** Must ship before Basic Auth is removed (production is internet-exposed). | P1-10 | S |

**Prepare the four-eyes architecture (no behaviour change):**
- Move all approval decisions into one policy function, `content.can_transition(user, version, target)`.
- It receives the version's `author` and `approved_by`.
- It is unit-tested for today's behaviour.
- A confirmed bank rule (B-1) then becomes a one-function change plus tests.

This is tracked as **A1-0** (S).

#### P1 — Pilot experience

| ID | Task | Audit ref | Size |
|---|---|---|---|
| A1-0 ✅ | Approval policy hook (see above), behaviour unchanged | P0-2 prep | S |
| A1-1 ✅ | Design system and application shell: sidebar, header, shared components, states (§3) — Phase 4A; page-level redesigns continue in A1-2…A1-10 | §17–19 | L |
| A1-2 ✅ | Live training screen redesign (§5) — Phase 5A | P1-3 | M |
| A1-3 ✅ | Results page redesign (§6) and `cap_reason` display — Phase 5A | P1-4 | M |
| A1-4 ✅ | Manager Overview, My Progress, History (§4.2) and endpoint `GET /me/progress` — Phase 5B | P1-5 | M |
| A1-5 | Compliance access to disputed scores: list, open session read-only, dispute status (open/reviewed) and reviewer note — *open: waits for B-2; needs additive dispute-status fields* | P1-6 | M |
| A1-6 ✅ | Approvals queue (pending scenario and KB versions) for approver roles; KB → dependent scenarios view; warning and confirmation before archiving a KB that live scenarios use — Phase 8 (queue via `can_transition`; archive confirmation lists live scenarios) | P1-7 | M |
| A1-7 ✅ | Structured editors for KB, scenario, client profile and scoring config, with advanced JSON view kept (§7) — Phase 7; the JSON view is read-only and the diff against the live version is not built yet | P1-8 | L |
| A1-8 | Admin: user search/filter, teams (lead, rename, deactivate, stats), confirmation dialogs — *partly, Phase 8: search, filters, confirmations, member counts; team rename/deactivate/lead not built* | P1-9 | M |
| A1-9 ✅ | Hide `/docs`, `/redoc` and `/openapi.json` in production; security headers (CSP, frame-ancestors, Referrer-Policy, X-Content-Type-Options) | P2-1, P2-2 | S |
| A1-10 | Lead workspace: sortable/filterable team table; separate Team and Performance views | P2-15, §11 | M |
| A1-11 | Training and catalogue duration hint (approximate minutes per difficulty, configurable per scenario, not invented per product) | §7 | S |
| A1-12 | End-to-end voice-turn latency: measure STT, LLM and TTS separately and show them on the dashboard | P2-8 | S |

#### P2 — Production hardening

| ID | Task | Size |
|---|---|---|
| A2-1 | Audit completeness: old → new values on `user.edit`; `session.finish`, `scoring.failed`, `auth.logout`, `team.edit` — *partly, Phase 8: `user.edit` now records old → new values* | S |
| A2-2 ✅ | Input limits: manager text length, audio size, per-user turn rate — Phase 9 (`app/limits.py`; per-user rate limit not built, post-pilot) | S |
| A2-3 | Cookie revocation: per-user `token_version` column bumped on logout-all or password reset (additive migration) | S |
| A2-4 ✅ | Persona-break guard line in the AI client prompt, plus a prompt test — Phase 9 (prompt rules + deterministic reply guard) | S |
| A2-5 | Unique `(session_id, turn_index)` constraint (additive; check existing data first) | S |
| A2-6 ✅ | CI: GitHub Actions running `pytest` on push and PR — Phase 9 (`.github/workflows/tests.yml`) | S |
| A2-7 | Adopt Alembic: baseline the current schema, keep `init_db` as wrapper | M |
| A2-8 | Dashboard aggregation moved to SQL (only if pilot volume requires it) | M |
| A2-9 | Remove stale comments and README paths; `init_db` step in the deploy checklist | S |
| A2-10 | Move `STT_VOCABULARY` to config (also a P3 enabler) | S |
| A2-11 | Remove production DB credentials from the local `.env.local` (process, not code) — *Phase 9: process item in `DEPLOYMENT_CHECKLIST.md` G (the app never reads `.env.local`; nothing committed)* | S |

#### P3 — Future SaaS (not in the pilot)
- **A3-1** Organizations and multi-tenancy (audit §7). Needs A2-7 first.
- **A3-2** SSO implementation; implementation depends on B-6 and B-7.
- **A3-3** Product management page (products are created implicitly today).
- **A3-4** Per-organization rubric, vocabulary and branding.
- **A3-5** Billing and usage metering.

### B — Requires a bank decision (do not implement)

| ID | Decision needed | What we prepare meanwhile |
|---|---|---|
| B-1 | **Four-eyes rules:** can an editor approve their own change? Must the approver differ from the author? Can the publisher be the approver? May admin bypass? | A1-0 policy hook; author and approver are already stored on every version |
| B-2 | **Who approves what:** product facts (product vs compliance vs both), scenarios (training vs product vs compliance) | Role sets are already isolated in `app/security.py` |
| B-3 | **External AI providers:** whether Anthropic, Deepgram and ElevenLabs are approved for conversation data | Provider interfaces (`app/providers/base.py`) allow a swap without touching the rest |
| B-4 | **DeepSeek specifically** (dialog model); approved alternative if refused | Same interface; a replacement dialog provider is a contained task once chosen |
| B-5 | **Allowed AI and data-processing regions;** Neon is currently in US-East | Nothing; region moves are infra changes |
| B-6 | **Hosting model:** SaaS (current Vercel + Neon), private cloud, or bank infrastructure | Dockerfile already exists; app is env-configured |
| B-7 | **SSO requirement and identity provider** | Identity seam documented (audit §8) |
| B-8 | **Account provisioning:** who creates users, team/lead structure | Admin user and team tools (A1-8) |
| B-9 | **Transcript, score and audit retention period;** deletion and export process | Data model already separates audio (never stored) from transcripts |
| B-10 | **Penetration-test requirements** | A0-6, A1-9 and A2-* close known findings first |
| B-11 | **Network restrictions** (IP allow-list, VPN) | None needed in code |
| B-12 | **Log export / SIEM** format and transport | Audit log is already structured JSON |
| B-13 | **Exact production security requirements** (password policy, session TTL, MFA) | Settings are already env-driven (`SESSION_TTL_HOURS`) |
| B-14 | **Whether Basic Auth stays** as an outer gate during the pilot | A0-6 makes removal safe |

### C — Requires bank content (never invented)

| ID | Content needed | Current state |
|---|---|---|
| C-1 | Approved **РКО** facts, arguments, objection responses, disclaimers | Developer placeholder, all facts `needs_review` |
| C-2 | Approved **Эквайринг** facts | Only `merchant_onboarding` (QR/wallet acceptance via Эсхата Онлайн) is published |
| C-3 | **Terminology:** is `merchant_onboarding` the bank's "Эквайринг" product, or is card acquiring a separate product? | Unconfirmed |
| C-4 | Approved **Зарплатный проект** facts | Placeholder |
| C-5 | Approved **Кредит для бизнеса** facts | Placeholder |
| C-6 | Approved **compliance restrictions** (forbidden formulations, critical errors) per product | Developer drafts per product |
| C-7 | **Approval of the 11 draft scenarios** (and of their client profiles, objections and weights) | Drafts tagged and versioned, waiting for review |
| C-8 | Pilot **duration hints and success metrics** per scenario, if the bank wants them shown | Not set |
| C-9 | **Compliance/Legal must confirm, replace, or remove the tax statement in `merchant_onboarding` objection `obj_taxes`** before pilot-approved content is considered complete | The published KB 1.0.0 contains the statement unresolved; its `compliance_note` requires compliance/legal confirmation before publication. Fix it through a new KB version: draft → `needs_review: true` on `obj_taxes` → resolution by Compliance/Legal → approve → publish. Engineering must not write the wording. `merchant_onboarding` is **not** fully pilot-approved while C-9 is open |

---

## 2. Frontend architecture decision

### What exists
- **Six static pages:** `index.html` 322 lines, `admin.html` 415, `dashboard.html` 254, `session.html` 42, `login.html` 42, plus the shared `app.js` 143, `theme.js` 37 and `app.css` 202. About 1,450 lines in total.
- **No build step, no npm, no node_modules.** Vercel serves `static/` through FastAPI's `StaticFiles`. Every page fetches JSON from the role-checked API.
- **All business rules and authorization live in the backend** (pytest-tested). The frontend holds no permission logic beyond hiding navigation.
- **Already shared:** `api()` error handling, `initPage()` nav guard, `esc()`, `renderResult()`, design tokens with light/dark.
- **Hardest upcoming UI:** the structured editors (A1-7), which edit nested arrays (KB facts, objections with responses, client profile `variants` lists), and six role workspaces with 6–9 pages each.

### Comparison

| Criterion | Option A — framework-free with shared components | Option B — lightweight framework (e.g. Vue/Preact/Svelte, with a build step) |
|---|---|---|
| Migration effort | None. New pages are written in the new style; old pages are refactored one at a time. | All 5 pages rewritten. Adds a build pipeline (npm, bundler) and a Vercel build config change; the legacy `builds` config in `vercel.json` already needed careful routing (audit §2). |
| Risk of breaking existing features | Low. Pages migrate one at a time behind the same API. | Medium. The voice recorder, polling and dispute flows are rewritten; the Vercel build and route change is the riskiest part. |
| Maintainability | Good **if** components are disciplined (one `ui/` module set, no copy-paste). It degrades if every page grows its own DOM code, which is the current `admin.html` trajectory. | Good; conventions are enforced by the framework. |
| Scalability for 6 workspaces | Adequate with a page-per-route structure and shared modules. The pain point is nested form state in editors. | Better: components plus reactive state handle nested editors and tables naturally. |
| Component reuse | Function components returning DOM (`Table()`, `Dialog()`, `Field()`) as native ES modules, with no bundler needed. | Native to the framework. |
| Forms | Needs a small form-binding helper for nested arrays (add/remove rows), written once (~150 lines). | Built in (two-way binding / controlled inputs). |
| Tables | One shared `DataTable` (sort, filter, empty/loading/error states) covers every list in the plan. | The same component, written in framework syntax. |
| State management | Per-page module state; nothing is shared across pages except `me` from `/auth/me`. That's sufficient: the server is the source of truth. | Framework stores; a benefit mostly for the editors. |
| Testing | Backend pytest stays the primary safety net. UI smoke tests would need a browser runner (Playwright), a new dev dependency to decide on separately. | Component tests become possible, but also need new tooling. Browser E2E is needed either way. |
| Development speed | Fast for shell, tables and dashboards; slower for the two structured editors. | Slower at first (setup, porting), faster for editors afterwards. |
| Code touched | Incremental: each page is touched when its workspace phase arrives. | Effectively all ~1,450 frontend lines, plus build and deploy config, before any new feature ships. |

### Recommendation for this repository

**Option A for the pilot, and decide on B after the pilot, based on evidence.**

Reasons specific to this codebase:
1. **The frontend is small and thin** (~1,450 lines, no logic of record). A rewrite would spend the pilot window re-creating working flows: the voice recorder, scoring polling, disputes and the dashboard charts.
2. **The deploy path is fragile.** It took a legacy `builds` workaround to make Vercel route correctly. Adding a build step changes the riskiest part of the deployment just before a bank pilot.
3. **The security model doesn't depend on the frontend** (backend RBAC, 43 tests). A framework would buy no safety, only developer ergonomics.
4. **The one place Option A hurts is the structured editors (A1-7).** That's contained by building one form-array helper and keeping the advanced JSON view as a fallback.

**How:** reorganise `static/` into `static/js/ui/*.js` (shell, table, dialog, toast, form, states), `static/js/pages/*.js` and one HTML entry per workspace. Use native ES modules (`<script type="module">`), with no bundler and no dependencies.

**Re-evaluate after the pilot.** Consider an incremental move to a framework if either of these holds:
- the editors exceed roughly 600 lines each, or
- multi-tenancy (P3) adds per-organization UI variation.

---

## 3. Shared shell and design system (A1-1)

| Element | Plan |
|---|---|
| **Layout** | Left sidebar (240 px, collapsible to icons at ≤1100 px, off-canvas drawer at ≤768 px) and a content area with a max width per page type (forms 880 px, tables and dashboards full width). |
| **Header** | Page title, breadcrumb for nested pages (Scenarios › Edit v3), right-aligned page actions. Global top bar: product name, theme switch (exists), profile menu. |
| **Role-aware navigation** | Built from `/auth/me` (role plus capability flags). Server enforcement is unchanged; the nav only hides links. A **direct URL to a forbidden page shows a "no access" state** with no data, because the API returns 403 (already the case). |
| **Profile menu** | Name, role, team, theme, change password (new endpoint: own password only, requires current password), log out. |
| **Page header component** | Title, subtitle, actions slot, optional tabs. |
| **Cards** | Used only for KPIs and summaries; lists use tables (avoid "giant cards everywhere"). |
| **Tables** | `DataTable`: column definitions, client-side sort, text filter, filter chips, sticky header, empty, loading-skeleton and error states. Below 768 px it collapses to a stacked list. |
| **Badges** | Status (draft, approved, published, archived), difficulty, verdict (approved, unsupported, forbidden), topic, "needs help". Colour from existing tokens, never colour alone (text label always present). |
| **Forms** | `Field` (label, hint, error), select, multiselect checkboxes, textarea, array editor (add/remove/reorder rows), inline validation messages from API 422 `detail`. |
| **Dialogs** | Native `<dialog>` wrapper with confirm/cancel; **destructive variant** requires typing or explicit confirmation text for: deactivate user, change role, publish, archive, end session. |
| **Loading** | Skeleton rows for tables, spinner inline for buttons (button disabled with label "Сохраняю…"). |
| **Empty states** | One sentence plus a primary action ("Нет опубликованных сценариев — их публикует команда обучения"). |
| **Error states** | Friendly message from the error-code map (A0-4), a "Повторить" button, and a technical reference ID (request ID) for support. No raw HTTP text. |
| **Toasts** | Success and failure for saves and status changes; auto-dismiss after 4 s; announced via `aria-live`. |
| **Typography and spacing** | System font stack (no external font dependency for a bank network); 4 px spacing scale; one type scale (12/14/16/20/24/32). |
| **Accessibility** | Contrast checked for both themes, visible focus ring, keyboard-operable dialogs and menus, mic button operable by keyboard (Space to hold). |

**Acceptance:**
- every existing page renders inside the shell;
- no page uses `alert()`;
- every list has empty, loading and error states;
- light and dark both pass a contrast check.

---

## 4. Page-by-page UX plan

### 4.1 Navigation per role

| Role | Sidebar |
|---|---|
| Manager | Overview · Training · My Progress · History · Settings |
| Sales Lead | Overview · Team · Performance · Training · Reports · Settings |
| Training | Overview · Scenarios · Training Programs · Performance · Reports · Settings |
| Product | Overview · Products · Knowledge Base · Performance · Reports · Settings |
| Compliance | Overview · Approvals · Disputed Scores · Knowledge Base · Scenarios · Audit Log · Reports · Settings |
| Admin | Overview · Users · Teams · Scenarios · Products · Knowledge Base · Reports · Audit Log · Settings |

**Reports (all roles):** for the pilot, one page with the dashboard's existing aggregates filtered to the role's permitted scope, plus CSV export of the visible table. No new analytics engine.

**Training Programs:** for the pilot, a read-only grouping of scenarios by topic and difficulty (data already exists). Assigning programs to managers is **out of scope**; it isn't LMS functionality.

### 4.2 Manager

| Page | Content | Data source |
|---|---|---|
| **Overview** | 1. Primary action: **Continue** (active session, if any) or **Start training** (recommended scenario). 2. Latest score with the cap reason if capped. 3. **Recommended next training:** the scenario whose topics match the weakest skill, else the next difficulty up. 4. **Weakest skill:** the lowest average criterion % over the last 5 sessions. 5. Progress sparkline of the last 10 scores. 6. Recent sessions (5). | New `GET /me/progress` (own data only; reuses `session_rows` plus criterion averages) |
| **Training** | Catalogue: product, difficulty and topic filters (exist); card shows title, product, difficulty, learning objective, approximate duration, topics. Briefing preview before start (visible fields only). | `GET /scenarios` (existing) |
| **Training Session** | See §5. | Existing session endpoints |
| **Results** | See §6. | `GET /sessions/{id}/score` plus `cap_reason` |
| **My Progress** | Score trend, per-criterion averages (bar list), per-product averages, critical-error history, topics practised. | `GET /me/progress` |
| **History** | `DataTable` of own sessions: date, scenario, product, difficulty, status, score, critical, disputed; actions Review, Repeat. | `GET /me/sessions` (existing) |
| **Settings** | Theme, change password. | New own-password endpoint |

No leaderboards, no gamification.

### 4.3 Sales Lead

| Page | Content |
|---|---|
| **Overview** | KPIs: active managers, sessions this week, average team score, trend, critical errors. "Needs help" list (top 5). Recent activity feed (team sessions only). |
| **Team** | `DataTable` with columns Manager, Sessions, Avg score, Trend (Δ vs previous period), Weakest skill, Critical errors, Last training. Sortable and filterable. A row opens the manager detail (sessions plus per-skill), and a session opens its read-only result and transcript. |
| **Performance** | Existing dashboard blocks: skills, products, weekly trend, risks; period filter. |
| **Training** | The lead's own catalogue (leads can train). |
| **Reports / Settings** | As §4.1. |

Isolation is unchanged: the server forces `team_id = lead.team_id` (tested).

### 4.4 Training

| Page | Content |
|---|---|
| **Overview** | Counts by status; recently changed scenarios; scenarios with low average scores; open disputes (aggregate, without names; already provided to training). |
| **Scenarios** | `DataTable` with columns Title, Product, Difficulty, Topics, Status, Live version, Latest version, Author, Updated. Search, filters, actions Edit, **Duplicate** (new endpoint: copies the latest version into a new draft scenario), Archive (with confirmation). |
| **Scenario Editor** | Structured (§7). Sections: Manager-visible context · Hidden client context · Learning objectives · Objections · Scoring · KB dependency (shows the product's published KB version and warns if none) · Version and publication metadata, with status actions per the approval policy. |
| **Training Programs** | Topic × difficulty grid of published scenarios (read-only). |
| **Performance** | Aggregate dashboard (no names). |
| **Reports / Settings** | As §4.1. |

### 4.5 Product

| Page | Content |
|---|---|
| **Overview** | Each product: live KB version, pending drafts, unreviewed-fact count, number of dependent scenarios. |
| **Products** | List of products with segment and live KB version. Creating a product stays an admin action (A3-3 later). |
| **Knowledge Base** | Per product, version history: version, status, author, updated, approved by, published at, notes. **"Currently approved truth" is visually distinct** from drafts. |
| **KB Editor** | Structured (§7). A diff vs the published version before submitting for approval. |
| **Performance** | Per-product averages, claim-verdict distribution, most frequent unsupported claims (aggregate). |
| **Reports / Settings** | As §4.1. |

### 4.6 Compliance

| Page | Content |
|---|---|
| **Overview** | Pending approvals count, open disputes, critical mis-selling events (last 30 days), forbidden-claim rate. Risk first. |
| **Approvals** | Queue of all `draft` versions awaiting approval and `approved` versions awaiting publication, for both scenarios and KBs. Each item shows a **diff against the live version**, author and age. Approve or reject actions per the approval policy (B-1); rejecting returns the item to draft with a mandatory comment (stored in `notes`, audited). |
| **Disputed Scores** | `DataTable`: date, scenario, score, critical errors, dispute text, status. Opens a read-only session (transcript, result, claims). Action "Mark reviewed" with a note. **Access rule:** compliance can open only **disputed** sessions and sessions with critical errors. This keeps the "no unnecessary personal data" principle, and should be confirmed with the bank as part of B-2. |
| **Knowledge Base / Scenarios** | Read access to the same views as Product and Training, with approve actions. |
| **Audit Log** | `DataTable` with filters (entity type, action, actor, date range) and CSV export. |
| **Reports / Settings** | As §4.1. |

### 4.7 Admin

| Page | Content |
|---|---|
| **Overview** | Users by role, active vs inactive, teams without a lead, recent admin actions. |
| **Users** | `DataTable`: search (name/login), filters (role, team, active), create/edit drawer. **Role change and deactivation require confirmation.** An admin can't demote or deactivate themselves (exists). |
| **Teams** | Name, lead (selected from `sales_lead` users; additive column `teams.lead_id`, or derived from users with role `sales_lead` in the team, decided in implementation), members count, active flag, average score. Rename, deactivate. |
| **Scenarios / Products / Knowledge Base** | Same pages as Training and Product, with all actions. |
| **Reports / Audit Log / Settings** | As above. Settings shows non-secret configuration (active providers, session TTL, Basic Auth on/off) read-only. |

---

## 5. Live training screen (A1-2)

| Element | Plan |
|---|---|
| **Client identity** | Header card: persona name, business type, role. Only `briefing()` fields, which are already the only ones the API returns. |
| **Business context** | Collapsible briefing panel (industry, size, current bank, situation) plus the conversation goal. |
| **Difficulty** | Difficulty badge and learning objective in the header. |
| **Timer** | Elapsed `mm:ss` from session start; soft hint at the scenario's suggested duration, never a hard stop. |
| **Mic state** | One button with explicit states: *Готов* → *Слушаю* (recording; level meter from the Web Audio analyser) → *Распознаю* → *Клиент думает* → *Клиент говорит* (playing; button disabled, "Прервать" available) → *Готов*. Space bar is push-to-talk. Clear guidance when mic permission is denied. |
| **Text fallback** | Always visible. Disabled only while a turn is in flight. |
| **Transcript** | Chat bubbles with per-turn latency (already present). **A bubble is added only after the server confirms it** (or shown as "pending" and turned into "failed" with retry). |
| **Graceful errors** | Error-code map (A0-4) → inline message in the transcript area, never `alert()`. |
| **Retry** | Text: the failed line keeps its text, and a "Повторить" button resends it. Voice: see the failure matrix (§9). |
| **Preserving input** | Text is never cleared until the server accepts the turn. For voice, the transcribed text is returned on dialog failure so the manager can resend it as text without re-speaking (A0-3). |
| **End session** | "Завершить" asks for confirmation ("Разговор будет оценён, продолжить нельзя"). It's disabled with an explanation if there are no turns. |
| **Hidden info** | Unchanged guarantee: no pains, hidden needs, objections or decision criteria in any API response (tested in A0-2). |

---

## 6. Results page (A1-3)

**Above the fold, readable in under 10 seconds:**
1. **Overall score** (large, `/100`), with a band label (e.g. "Нужно доработать" / "Хорошо" / "Отлично"). Band thresholds are a product decision; the default proposal is <60 / 60–79 / ≥80.
2. **Critical errors**, if any: a red block, one line each, with the quote.
3. **Why the score was capped** (A0-5): "Итог ограничен 60 баллами, потому что: …". It lists the critical errors and/or unsupported or forbidden claims that triggered the cap.
4. **One key takeaway:** the feedback `summary`, plus a **Recommended next skill** chip.

**Below:**

5. **Criterion breakdown:** horizontal bars per criterion (score/max, scenario weight if overridden). Each bar expands to show the reason and the quote.
6. **Strengths.**
7. **Areas for improvement.**
8. **Important conversation moments:** turns referenced by quotes, critical errors or claims, each linking to the transcript position.
9. **"What you said → Better version"** pairs (`better_examples`).
10. **Claims** grouped into three labelled groups: *Подтверждено БЗ* / *Нет в БЗ* / *Запрещено*, each with the turn link and reason.
11. **Recommended next skill** with a link to a matching scenario (by topic).
12. **Actions:** *Repeat this scenario* (primary), *Choose another*, *Dispute the score* (exists).

Version footer: scenario vN · KB vX (exists; keeps auditability visible). The same component is used for the lead/admin/compliance read-only view (actions hidden; dispute visible read-only).

---

## 7. Structured editors (A1-7)

Common rules:
- **Every editor has an "Advanced: JSON" tab.** It is shown to admin always, and to other roles behind an explicit toggle. Both views edit the same object and validate through the same server endpoint (`validate_kb_content`, `validate_scenario_content`), so the server stays the single validator.
- **Unknown fields are preserved.** Fields the form doesn't know are kept untouched, so nothing is lost.
- **Read-only when not a draft,** with a "Create new version" action (existing behaviour).
- **Diff vs the live version** before submitting for approval.

| Editor | Sections |
|---|---|
| **KB** | Product (name, segment) · **Approved facts** (rows: id auto, type, text, `needs_review` checkbox, which is visible and must be cleared before approval, per A0-1) · Approved arguments · Objections (trigger → approved response, `compliance_owned` flag) · Disclaimers · Forbidden formulations (list) · Critical errors (list) · Version notes |
| **Scenario** | Basics (title, product, difficulty, topics, rubric) · Manager-visible (goal, learning objective, briefing fields) · Hidden client context (pain, hidden need, decision criteria, emotion, urgency, trust, objections) · Learning (good examples, feedback hints) · Scoring (§ below) · KB dependency (read-only status of the product's published KB) |
| **Client profile** | Each profile field is a single value **or** a list of variants (toggle per field). The visible/hidden split is shown with a label on every field, driven by `BRIEFING_FIELDS`, so authors always know what managers will see. |
| **Scoring config** | Rubric criteria with default weight and override input; live total; warning if all weights are 0 (server rule exists); read-only display of the 60-cap rule and the critical-error → criterion map. |

---

## 8. Test plan

Test types: **U** unit · **I** in-process API integration (current `TestClient` style, stub providers) · **G** gate test with the real model (manual or nightly, costs money) · **M** manual QA.

| Area | Existing coverage | Missing | Type | Priority |
|---|---|---|---|---|
| Authentication | `test_api_requires_login`, `test_wrong_password_rejected`, `test_tampered_cookie_rejected`, `test_logout`, `test_health_is_public` | Login throttling (A0-6); failed-login audit; expired token | I | P0 |
| Authorization (role routes) | `test_dashboard_roles`, `test_user_admin_is_admin_only`, `test_audit_log_access`, `test_aggregate_role_cannot_start_session` | KB and scenario edit/approve/publish per role (every route × role); `/kb/{id}` hidden from managers | I | P0 |
| Team isolation | `test_session_visibility` (lead same team), `test_lead_cannot_open_other_team`, `test_dashboard_names_only_for_lead_and_admin` | Lead with no team (409); lead dashboard ignores a `team_id` query param | I | P1 |
| Session ownership / IDOR | `test_session_visibility`, `test_only_owner_can_write` | Turn, voice-turn, finish, score-run and audio by non-owner; random session id (404) | I | P0 |
| Hidden scenario fields | — | `/scenarios` and `POST /sessions` responses never contain pain, hidden_need, objections, decision_criteria (seed every scenario) | I | P0 |
| KB enforcement | `test_manager_sees_only_published_scenarios`, `test_draft_scenario_cannot_be_started` | Scenario publish blocked without published KB; **unreviewed KB cannot be approved or published (A0-1)**; AI prompt contains only the bound KB version's facts | U + I | P0 |
| Unsupported claims | Gate fixtures (manual) | `has_critical_error` true for an `unapproved` verdict alone; result exposes `cap_reason` | U + I | P0 |
| Forbidden claims | Gate fixtures (manual) | Same for `forbidden`; claim rows persisted with verdicts | U + I | P0 |
| Critical errors | Gate fixture (manual) | Critical-error entry triggers the cap; stored on `Score`; audited in `session.scored` | U + I | P0 |
| Scoring arithmetic | — | `effective_weights` overrides and negatives; `compute_total` normalisation, scores clamped to max, zero-weight criteria skipped, all-zero weights → 0 | U | P0 |
| 60-point cap | — | 100-point breakdown + critical → 60; 40-point + critical → 40 (cap never raises) | U | P0 |
| Scenario version linkage | `test_full_session_flow` (partial) | Publish v2 mid-session → existing session still uses v1 content and prompt; result shows v1 | I | P0 |
| KB version linkage | — | Publish KB v2 mid-session → the session's prompt and claim check use v1; result shows v1 | I | P0 |
| Scenario publication | `test_scenario_topics_validated_and_saved` (validation only) | Full lifecycle with allowed and forbidden transitions per role; publishing archives the previous version | I | P1 |
| KB publication | — | Lifecycle; publishing archives the previous version; approved/published versions immutable (409 on edit) | I | P1 |
| Approval policy hook | — | A1-0 policy reproduces current rules exactly (table-driven) | U | P1 |
| AI provider failures | `test_slow_scoring_ends_as_retryable_error` | Dialog error/timeout → transcript unchanged, friendly error code; STT error → no turn saved, error code; TTS error in voice turn → turns returned without audio, not a 500; scoring provider error → `finish_error` with safe message (no raw text) | I | P0 |
| Session persistence | `test_full_session_flow` | Turn indexes contiguous after a failed turn; finish requires ≥1 turn; retry after `finish_error` re-scores cleanly | I | P1 |
| Results visibility | `test_session_visibility` | Compliance can open disputed or critical sessions only (A1-5); dispute status changes are audited | I | P1 |
| Security headers / docs | — | Headers present; `/docs` and `/openapi.json` 404 in production mode | I | P1 |
| UI flows | — | Scripted manual QA per role (§10). Browser automation (Playwright) is a separate dev-dependency decision, not assumed | M | P1 |

The gate test (`tests/run_gate_test.py`) stays as the real-model check for mis-selling detection. Run it manually before each pilot release (it costs API credit).

---

## 9. AI failure handling

### Current behaviour (from code)
- **Timeouts:** Deepgram, DeepSeek and ElevenLabs each have a 30 s `httpx` timeout and no retry. Anthropic uses SDK defaults (2 retries), bounded by the 270 s scoring budget.
- **Unhandled provider exceptions** in turn endpoints become HTTP 500 with a plain-text body. The UI then shows "Ошибка: HTTP 500".

### Failure matrix

| Provider / step | Timeout → today | Error → today | Manager sees today | Input lost today? | Recommended behaviour | Session can continue? |
|---|---|---|---|---|---|---|
| **Deepgram** (STT, voice turn) | 30 s, then 500 | 500 | "Ошибка: HTTP 500" | **Yes:** audio is discarded by design (never stored) | Return `stt_unavailable` (502) with "Не удалось распознать речь — повторите или напишите текстом". Keep the audio Blob **in browser memory only** for one automatic resend; never persist it server-side. | Yes. Nothing was saved. |
| **Deepgram** empty result | — | 400 "пустая реплика — речь не распознана" | That message | Audio yes (nothing said) | Keep as is, friendlier copy. | Yes |
| **DeepSeek** (text turn) | 30 s, then 500; transaction rolled back | 500 | Error bubble; **the manager's bubble stays on screen but isn't stored** | Not stored; the text is still in the bubble but the input was cleared | Return `dialog_unavailable` (502) and keep the input text. The UI marks the line "не отправлено" with retry. One server-side retry on timeout or 5xx (idempotent: nothing is committed before success). | Yes |
| **DeepSeek** (voice turn) | as above | as above | Error bubble; transcribed text never shown | **Yes:** STT text is lost and the manager must re-speak | Return `dialog_unavailable` **with `manager_text`** so the UI shows it as a pending line with "Отправить ещё раз" (sent via `/turns`, no re-STT). | Yes |
| **ElevenLabs** (voice turn) | 30 s, then 500 **after** both turns were committed | 500 after commit | Error; **stored turns aren't shown, so a retry duplicates them** | No, but the screen and transcript diverge | Commit first, then synthesize; on TTS failure return 200 with the turns and `audio_error: true`. The UI shows the text with "Озвучка недоступна — прочитайте ответ". Optional "Озвучить" retry via the existing audio endpoint. | Yes (text-only for that turn) |
| **ElevenLabs** (text turn audio GET) | 30 s | 500 on the audio URL | Silent; `play()` errors are swallowed | No | Show a small "озвучка недоступна" marker with replay. | Yes |
| **Anthropic** (scoring) | Bounded at 270 s → `finish_error` (tested) | `finish_error` with **raw `str(exc)`** shown to the manager | "Ошибка оценки: <raw provider text>" | No: the transcript is intact | Store the raw error in logs; return a code such as `scoring_unavailable` plus friendly copy and "Повторить оценку". The existing retry path (`/finish` from `finish_error`) is kept. | The conversation is closed; scoring can be retried safely (idempotent claim) |
| **Anthropic** invalid key / 4xx | Immediate `finish_error` | as above | raw text | No | Same, plus a server-side alert (log at ERROR). Retry won't help, so after 2 failures show "Оценка временно недоступна, результат появится позже" and keep the session in `finish_error` for an admin re-run. | As above |
| **Network loss in browser** | — | `fetch` throws | "сеть недоступна (…)" | Text input kept only if not cleared (currently cleared) | Keep input; offer a retry banner; status poll resumes (already resumes for scoring). | Yes |

**Principles:**
- The screen always equals the stored transcript.
- Nothing is committed for a turn until the dialog reply succeeds.
- TTS is non-critical: it degrades to text.
- Audio never touches the server's disk or DB, including on retry.
- No raw provider messages reach users.

---

## 10. Security plan

| Item | Current behaviour | Risk | Proposed change | Files | Tests | Regression risk |
|---|---|---|---|---|---|---|
| **Login rate limiting** (A0-6) | Unlimited attempts; failures not audited | Password guessing once Basic Auth is removed | Per-username **and** per-IP counters (e.g. 5 failures per 15 min → 429 with retry-after). The store must work on serverless: a small DB table (`login_attempts`, additive), since in-memory counters reset per Vercel instance. Audit `auth.login_failed` (username only, never the password). | `app/routers/auth.py`, `app/models.py`, `app/main.py` (`_add_missing_columns`/table) | Lockout after N failures; reset after success; per-IP limit; audit row written | Low: demo/test logins must not trip it (test fixture resets) |
| **`/docs` exposure** (A1-9) | `/docs`, `/redoc`, `/openapi.json` live (behind Basic Auth only) | API map public if Basic Auth dropped | `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` unless `ENABLE_API_DOCS=true` (default true locally, false in production) | `app/main.py`, `app/config.py` | 404 when disabled | None for users |
| **Security headers** (A1-9) | None set by app | Clickjacking; MIME sniffing | Middleware: `Content-Security-Policy: default-src 'self'; img-src 'self' data:; media-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'`, plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`. HSTS is already added by Vercel; add it in the app for non-Vercel hosting. | new `app/headers.py`, `app/main.py` | Headers present on pages and API | **Medium:** inline scripts and `data:` audio must stay allowed; the plan moves inline scripts into modules (§2) so `'unsafe-inline'` can be dropped later |
| **Cookie configuration** | HttpOnly, SameSite=Lax, Secure on HTTPS, 12 h, HMAC-signed; not revocable | Stolen or remaining cookie valid until expiry after logout or password reset | A2-3 `token_version` per user, included in the signed payload; bump on password change and "log out everywhere". Keep SameSite=Lax (Strict would break deep links from email). TTL stays env-driven (B-13). | `app/security.py`, `app/models.py`, `app/routers/admin.py` | Old cookie rejected after password reset | Low: all existing sessions are logged out once on deploy (acceptable, announce it) |
| **Authorization** | Server-side role dependencies; matrix in one file; tested | Drift as new endpoints are added | Every new endpoint gets a role-matrix test row (§8). A1-0 centralises approval rules. A1-5 adds a **narrow** compliance read rule (disputed or critical sessions only). | `app/security.py`, `app/main.py` (`_load_session`) | Table-driven route × role tests | Low |
| **IDOR** | `_load_session` on every session route; IDs are random UUID hex | Low today | Keep; add the non-owner tests for every session sub-route (§8). New endpoints (`/me/progress`, dispute review) must derive the user from the cookie, never a path param. | — | §8 rows | None |
| **Transcript access** | Owner, same-team lead, admin; aggregate roles blocked | Compliance needs dispute review without broad access | Add only the disputed/critical-session rule (pending B-2 confirmation; default off behind a setting until confirmed) | `app/main.py` | Compliance can open a disputed session, not a non-disputed one | Low |
| **Secrets** | Env only; none in git history (verified); `.env.local` on a dev laptop holds production DB credentials | Laptop compromise exposes the production DB | A2-11 rotate the Neon password after the pilot setup; use `vercel env pull` only for development DBs. Add a `secrets in repo` check to CI (A2-6). | process + CI | CI secret scan | None |
| **Production error messages** (A0-4) | Raw exception text in `finish_error` and HTTP 500 bodies | Leaks provider internals; confusing UX | Global exception handler: log full error with a request ID; respond with `{code, detail(ru), request_id}`. `scoring_error` stores the code, not the raw text (raw text goes to logs). | `app/main.py`, `static/js/ui/*` | Provider failure → no raw text in response | Low |

No infrastructure migration is part of this plan.

---

## 11. Pilot flows (expected end-to-end)

| Role | Flow | Notes |
|---|---|---|
| **Manager** | Login → Overview → Select Training → Scenario briefing → Voice session → Finish (confirm) → Scoring (progress state; up to 270 s) → Results → My Progress → Repeat | Text fallback available at every turn |
| **Sales Lead** | Login → Overview → Team → Manager performance → Training result (read-only, with transcript) | Own team only |
| **Training** | Login → Scenarios → Create / Edit draft → **Submit for approval** → (approver approves per B-1/B-2) → Publish | Publishing is blocked unless the product KB is published and clean (A0-1) |
| **Product** | Login → Knowledge Base → Edit product facts (new draft version) → Clear `needs_review` → Submit → (approved per B-1/B-2) → Publish → dependent scenarios now train on the new version | Earlier sessions keep their old KB version |
| **Compliance** | Login → Approval queue → Review diff → Approve / Reject with comment (per confirmed policy) → Disputed scores → Mark reviewed → Audit log | Approve rules await B-1 |
| **Admin** | Login → Users (create, role, team; confirmations) → Teams (lead, members) → Audit log | Can't lock themselves out |

"Submit for approval" is a UI label for the existing `draft` state plus an entry in the approvals queue. No new status is introduced unless B-1 requires one.

---

## 12. Implementation phases

| Phase | Tasks | Size | Depends on | Risk | Acceptance criteria |
|---|---|---|---|---|---|
| **1 — Safety and correctness** ✅ done | A0-1 (unreviewed KB guard), A0-5 (cap reason), A1-0 (approval policy hook, no behaviour change) | S | — | Low: server-only, additive | Placeholder KBs can't be approved or published (409 lists unreviewed IDs); every capped result returns a non-empty `cap_reason`; approval behaviour identical (tests) |
| **1b — Scoring and content safety gaps** ✅ done | Fix duplicate/unknown/missing evaluator criteria (provider retry + first-occurrence safety net), fail-closed claim verdicts (provider retry + backend normalisation), hide draft-only products from `/products` for manager and lead | S | Phase 1 | Low | See `PHASE_1B_IMPLEMENTATION.md` |
| **2 — Tests** ✅ done (except Phase 3-dependent rows) | All P0 rows of §8 (scoring math, cap, hidden fields, version linkage, KB enforcement, IDOR on session sub-routes, role × route matrix for content) | M | Phase 1 | Low | P0 rows of §8 green; suite runs offline in under 10 s |
| **3 — Reliability and security basics** | A0-3, A0-4 (failure matrix §9), A0-6 (login throttling), A1-9 (docs off, headers), A2-6 (CI) | M | Phase 2 | **Medium:** turn-commit ordering and CSP touch live flows | Each row of §9 has a passing failure test; no raw provider text in any response; lockout works; headers present; CI runs on PR; Basic Auth can be removed (B-14) |
| **4 — Design system and app shell** | A1-1: restructure `static/` into ES modules (§2), shell, sidebar, components, states; migrate existing pages into the shell **unchanged in behaviour** | L | Phase 3 (error-code map) | **Medium:** touches every page; mitigated by migrating one page at a time and a per-page manual QA script | Every current page works in the shell; no `alert()`; empty, loading and error states everywhere; light and dark contrast pass |
| **5 — Manager experience** | A1-2 (session screen), A1-3 (results), A1-4 (overview, progress, history, settings), A1-11 (duration hint) | M–L | Phases 3, 4 | Medium: voice UX on real devices | Manager flow §11 passes on Chrome, Edge and Safari (desktop); a result is understandable in <10 s (hallway test with 3 people); input never lost in §9 scenarios |
| **6 — Management workspaces** | A1-10 (lead team/performance), Training overview and Programs, Product overview and performance, Reports with CSV | M | Phase 4 | Low | Lead sees only own team (tests); every table sortable and filterable; CSV export matches the visible table |
| **7 — Content editors** | A1-7 (KB, scenario, client profile, scoring config editors with advanced JSON), scenario Duplicate, KB → dependent scenarios, diff vs live | L | Phase 4 | **Medium–high:** nested forms; data loss risk mitigated by "unknown fields preserved" and server-side validation | A non-technical user can create a KB draft and a scenario draft without JSON; round-trip form ↔ JSON is lossless (test); diffs shown before submit |
| **8 — Compliance and admin** | A1-5 (disputes access and review), A1-6 (approvals queue, archive warnings), A1-8 (users search, teams, confirmations), A2-1 (audit completeness) | M | Phases 4, 7; A1-5 access rule pending B-2 | Low–medium | Compliance flow §11 passes; dangerous actions confirm; audit records old → new values |
| **9 — Pilot QA** | Full suite, gate test with real Claude, scripted manual QA per role (§11) on production-like data, latency measurement (A1-12), the remaining P2 items needed for go-live (A2-2, A2-3, A2-5) | M | Phases 1–8 | Low | `PILOT_READINESS_CHECKLIST.md` "READY" section complete; median voice-turn latency recorded |
| **10 — Bank-dependent configuration** | Apply B-1/B-2 (four-eyes rule in the policy hook), load C-1…C-7 content through the editors and publish via the approval flow, B-3/B-4 provider decisions, B-6 hosting, B-9 retention, B-7 SSO if required (P3 unless mandated) | S–L depending on decisions | Bank decisions and content | Depends on decisions: a provider swap (B-4) or hosting move (B-6) is the largest | All 4 products with approved KBs; 12 scenarios published through the approval flow; decisions recorded in the checklist |

**Outside this plan (P3):** multi-tenancy (A3-1, after Alembic A2-7), SSO implementation unless mandated, product management page, billing.

**Critical path:** Phases 1 → 2 → 3 are short, server-only and unblock everything else. Phase 4 is the largest engineering risk. Phase 10 is the largest schedule risk, because it waits on bank content and decisions. **Request C-1…C-7 and B-1…B-4 from the bank now,** in parallel with Phase 1.

---

## Remaining gates before deployment (after Phase 8)

Full detail: `PHASE_8_IMPLEMENTATION.md`.
- **Engineering P0:** none known.
- **Engineering P1:** A2-2, A2-4 and A2-6 were done in Phase 9. What remains:
  - config: separate the Preview database and set `CLIENT_IP_HEADER`;
  - A2-11 (process);
  - dispute review fields after B-2.
- **Bank decisions:** B-1…B-14, plus B-15 (historical team membership and deactivated managers in team numbers) and B-16 (compliance seeing per-manager score events in the audit log).
- **Bank content:** C-1…C-9. C-9 (`obj_taxes`) blocks declaring the merchant content pilot-approved.
- **Pilot QA:** the Phase 9 plan is in `PHASE_9_LAUNCH_READINESS.md` §11. Still open:
  - real-provider gate run (paid, needs approval);
  - voice latency on Vercel;
  - microphone and audio on bank devices;
  - STT quality;
  - deployment checklist and backup/restore;
  - six-role walkthrough on the deployed build.

