# Pilot Readiness Audit — AI Voice Trainer

**Date:** 2026-10-05 · **Commit audited:** `da4b55d` (branch `vercel-deploy`, live at https://ai-voice-trainer-weld.vercel.app)
**Scope:** Phase 1 only — inspection, no implementation. Every finding below comes from reading the code or from live checks run during the audit; where something was not verified it says so.

Priorities: **P0** pilot blocker · **P1** important before pilot · **P2** improvement · **P3** future SaaS work. **[BANK]** marks items that need a bank decision or bank-supplied material and cannot be resolved by engineering alone.

---

## 1. Executive summary

The core loop already works end to end in production: login → choose scenario → voice or text conversation (Deepgram → DeepSeek → ElevenLabs) → finish → two-pass Claude scoring (claim verification against the KB, then rubric scoring) → results → history. Role checks are enforced on the server, sessions are bound to the exact scenario and KB version, the 60-point cap is applied deterministically in Python, audio is never stored, and there are 43 passing access-control tests.

What separates it from a bank pilot is mostly **content and controls**, not architecture:

1. Only **1 of 12 scenarios** and **1 of 4 products** are approved. The other three knowledge bases are developer placeholders, and nothing on the server stops someone from publishing them as "approved truth" (P0).
2. The KB approval chain has **no four-eyes control**: compliance can edit a KB and then approve its own edit, and an admin can run the whole chain alone (P0).
3. Several role workspaces are thin. Compliance has no approvals queue and can't see disputes. Managers have no progress view. Product and Training edit raw JSON (P1).
4. **Provider failures surface as raw errors** mid-conversation, and in voice mode the manager's utterance is lost (P1).
5. Several items need **bank decisions**: whether transcripts may be sent to DeepSeek, Anthropic, Deepgram and ElevenLabs; hosting; retention; SSO; and user provisioning.

**Estimated pilot readiness: ~60 %** (engineering core ~85 %, RBAC/security ~75 %, role UX ~45 %, approved content ~10 %, bank/ops decisions ~0 %).

---

## 2. Architecture as built

| Layer | Implementation |
|---|---|
| Backend | FastAPI (async), single app `app/main.py` + routers `auth`, `admin`, `dashboard` |
| DB | SQLAlchemy async; SQLite locally, Neon Postgres in production (NullPool, `statement_cache_size=0`, SSL) |
| Schema migrations | `init_db()` = `create_all` + additive `_add_missing_columns`; run manually via `scripts/init_db.py` on Vercel (`AUTO_INIT_DB=false`) |
| Frontend | Static HTML + vanilla JS (`static/*.html`, `app.js`, `theme.js`, `app.css` design tokens, light/dark) — no build step, no framework |
| Auth | Own login: PBKDF2-SHA256 (200k) passwords, stateless HMAC-signed cookie (`avt_session`, 12 h, HttpOnly, SameSite=Lax, Secure on HTTPS); optional outer HTTP Basic Auth gate (`app/auth.py`, currently ON in production) |
| RBAC | Single matrix in `app/security.py`; `require_roles()` dependencies; per-session access in `_load_session()` |
| AI | `app/providers/*` behind ABCs (`base.py`), chosen by env: Deepgram nova-3 STT, DeepSeek chat dialog, Claude `claude-sonnet-5` scoring (streaming, structured JSON output), ElevenLabs `eleven_multilingual_v2` TTS; `stub` implementations for tests |
| Hosting | Vercel (legacy `builds`/`routes`, fluid compute, 300 s function limit) + Neon; Dockerfile + `railway.json` also present (container path) |
| Tests | `tests/test_access.py` (43 in-process tests, stub providers, temp SQLite); `tests/run_gate_test.py` (manual mis-selling gate against real Claude, needs running server) |

---

## 3. What already exists and works (verified)

### Training loop
- **Scenario catalogue** shows only scenarios whose published version belongs to a product with a published KB (`GET /scenarios`).
- **Session creation** binds `scenario_version`, `kb_version`, `rubric_id` and a generated client profile to the session (`POST /sessions`). It's audited as `session.start`.
- **Hidden information stays hidden.** The manager receives only `briefing()` fields (persona, business type, industry, size, employees, role, current bank, situation). Pains, hidden needs, objections and decision criteria never leave the server.
- **Client generation.** Each session draws a different client from `client_profile.variants` (`app/client_generator.py`).
- **AI client prompt** (`app/prompts.py`): concise answers, progressive disclosure, objections, no coaching, no confirming conditions absent from approved facts, plus difficulty rules for easy, medium and hard. KB facts are injected from the session's bound KB version only.
- **Voice turn:** STT → dialog → TTS. Audio bytes are deleted right after transcription and never written to disk or the DB. Replaying audio re-synthesises it from the text.
- **Live latency** (2026-10-05): DeepSeek reply 0.67–0.90 s; a full voice turn worked end to end.

### Scoring
- **Two passes.** Pass 1 verifies claims against the KB (`approved | unapproved | forbidden`, including approved arguments and objection responses). Pass 2 scores against the rubric with those verdicts treated as ground truth.
- **Rubric** `rubric_sales_100` matches the requested criteria and weights exactly. Contact 10 · Needs 15 · Questions 10 · Listening 10 · Relevance 10 · Value 10 · Objections 10 · Correctness 10 · No mis-selling 10 · Next step 5.
- **Deterministic total** (`app/scoring_math.py`). The model never computes the total. Scenario weight overrides are normalised to 100, and the result is capped at 60 when there is a critical error or an unapproved/forbidden claim.
- **Critical error → criterion map** is defined in the rubric, so each error type zeroes exactly one criterion.
- **Explainability:** each criterion carries a reason and a quote; feedback includes summary, strengths, growth areas, "Было / Лучше" examples and next skill.
- **Scoring runs out of band** (`/finish` → `/score-run` + polling) with a 270 s budget under Vercel's 300 s limit. An overrun ends as a retryable `finish_error`; this is tested. A live Claude scoring run took about 37 s.
- **Gate fixtures** for honest and mis-selling dialogues exist in `tests/fixtures/` as reference results.

### Content governance
- **Lifecycle:** scenario versions and KB versions follow draft → approved → published → archived (`check_transition`). Approved and published versions are immutable; editing creates a new draft. Publishing archives the previous version.
- **Dependency:** a scenario can't be published until its product has a published KB.
- **Insert-only seed loader:** the admin panel is the source of truth after first load. Topic backfill touches only versions without topics.
- **Topics:** 7 training topics, validated server-side, filterable in the catalogue.

### RBAC and isolation (covered by tests)
- **Authentication:** every API route except `/health` and `/auth/login` requires login. Deactivated users are rejected on the next request.
- **Sessions:**
  - The owner can read and write.
  - A sales lead can read only sessions of managers in their own team.
  - An admin can read all sessions.
  - Training, product and compliance can never open individual transcripts.
- **Dashboard:**
  - A sales lead is forced to their own team.
  - Aggregate-only roles get no names.
  - `/dashboard/managers/{id}/sessions` checks the target's team.
- **Admin:** user and team management is admin-only. An admin can't deactivate or demote themselves. The audit log is admin and compliance only.
- **XSS:** all model and user text rendered in the browser goes through `esc()`. A heuristic scan of every template interpolation found no unescaped strings.

### Audit
Logged actions:
- `auth.login`
- `session.start` and `session.scored` (with scenario/KB version, total and critical error types)
- `score.dispute`
- `scenario.create`, `scenario.edit_draft`, `scenario.new_version`, `scenario.status` (from → to)
- `kb.new_version`, `kb.edit_draft`, `kb.status` (from → to)
- `user.create` and `user.edit` (role/team/active changes; a password reset is logged as `"reset"`, never the value)
- `team.create`

Audit rows commit in the same transaction as the change they describe.

---

## 4. Findings

### P0 — pilot blockers

| ID | Finding | Evidence | Why it blocks |
|---|---|---|---|
| **P0-1** ✅ *fixed in Phase 1* | **Placeholder KB content can be approved and published.** `rko`, `payroll_project` and `business_loan` KBs are developer placeholders: every fact has `needs_review: true` and a `draft_note` says "НЕ является утверждённым продуктовым контентом". The server checks neither on approve or publish; only the admin UI shows a warning. | `app/routers/admin.py` `set_kb_status`; `app/content.py` `validate_kb_content` | Breaks the core principle: developer-written text could become the "approved truth" the AI client and scorer rely on. |
| **P0-2** ⏸ *bank decision B-1/B-2; policy hook added in Phase 1* | **No four-eyes control on product truth.** `compliance` is in both `KB_EDIT_ROLES` and `KB_APPROVE_ROLES`, and approval doesn't check that the approver isn't the version's author. An `admin` can create, approve and publish a KB or scenario alone. | `app/security.py` role sets; `check_transition` | A bank's compliance sign-off is meaningless if the editor can approve their own change. |
| **P0-3 [BANK]** | **Approved content covers 1 of 4 products and 1 of 12 scenarios.** Only `merchant_onboarding` (KB 1.0.0) and its medium scenario are published. The other 11 scenarios can't be published until the bank supplies and approves product facts. | `seed/knowledge_base.json`, `seed/scenarios.json`, live `/scenarios` | The MVP scope (4 products × 3 levels) can't be piloted. Engineering must not invent the facts. |
| **P0-4 [BANK]** | **Approval to send transcripts to external AI processors.** Every conversation goes to DeepSeek; every manager utterance's audio to Deepgram; client lines to ElevenLabs; full transcripts plus KB to Anthropic. DeepSeek's API is hosted outside the bank's likely data jurisdiction. | `app/providers/*` | A bank security or legal decision is needed before real employees use it. This may force a provider change for the dialog model. |

### P1 — important before pilot

**Conversation and UX**

| ID | Finding | Evidence |
|---|---|---|
| P1-1 | **Provider failures surface as raw errors.** A DeepSeek, Deepgram or ElevenLabs exception becomes an unhandled 500; the UI shows "Ошибка: HTTP 500". In text mode the manager's bubble stays on screen although the turn was rolled back, so the screen and the transcript disagree. In voice mode the utterance is lost and must be re-spoken. Provider timeouts are 30 s each with no retry. | `_process_manager_turn`, `post_voice_turn`, `static/index.html` `sendTurn`/`sendVoiceTurn` |
| P1-2 ✅ *fixed in Phase 1* | **Silent score cap.** The cap triggers on any `unapproved` or `forbidden` claim verdict even when the model returned no `critical_errors` entry, but the result page explains the cap only when `critical_errors` is non-empty. A manager could see "58/100" with no reason. | `scoring_math.has_critical_error` vs `renderResult` in `static/app.js` |
| P1-3 | **Session screen is not simulation-grade.** There's no elapsed timer, no listening/processing/speaking states (only "Клиент думает…"), no client identity header during the call, no estimated duration in the catalogue, and errors use `alert()`. | `static/index.html` |
| P1-4 | **Results page has no hierarchy.** All the content is present: score, criteria with quotes, critical errors, claims, feedback, next skill and repeat. It renders as one long flat list. Claims aren't grouped into approved / unsupported / forbidden, and there are no links to transcript moments. | `renderResult` in `static/app.js` |
| P1-5 | **Manager workspace lacks progress.** The home page is catalogue plus history. There's no latest score, trend, weakest skill or "recommended next training". | `static/index.html` |

**Role workspaces**

| ID | Finding | Evidence |
|---|---|---|
| P1-6 | **Compliance can't review disputes or risky sessions.** The dashboard returns `disputes` only to named views (lead, admin) and `training`. Compliance gets an empty list and is blocked from transcripts by `_load_session`. Disputes also have no status (open/resolved) or reviewer response. | `app/analytics.py` line ~288; `Score` model |
| P1-7 | **No approvals queue.** Compliance and product must open each scenario or KB to find pending versions. There's also no view of which scenarios depend on a KB version, and no warning when archiving a published KB that live scenarios use. | `static/admin.html`, `set_kb_status` |
| P1-8 | **Content editing is raw JSON.** The KB is edited as a JSON textarea, and the scenario client profile is a JSON blob that mixes visible briefing fields with hidden ones. That isn't workable for non-technical product or compliance staff, and makes accidental exposure of hidden fields more likely. | `static/admin.html` (`kb-data`, `s-profile`) |
| P1-9 | **Admin users and teams pages are basic.** There's no search or filter on users, scenarios or audit. Teams have no lead, no rename, no deactivate and no stats. There are no confirmation dialogs for dangerous actions such as deactivating a user, changing a role, publishing or archiving. | `static/admin.html` |

**Security**

| ID | Finding | Evidence |
|---|---|---|
| P1-10 | **No login throttling or lockout.** `/auth/login` allows unlimited attempts. Basic Auth mitigates this today, but it's meant to be removed. Failed logins aren't audited. | `app/routers/auth.py` |

**Tests**

| ID | Finding | Evidence |
|---|---|---|
| P1-11 | **Critical business logic is untested.** Specifically: `scoring_math` (weights, normalisation, cap), the claim-verdict-driven cap, the prompt never containing unpublished KB content, the briefing never containing hidden fields, version binding when a new version is published mid-session, and scenario publish being blocked without a published KB. | `tests/` |

### P2 — improvements

**Security**
- **P2-1** **`/docs` and `/openapi.json` are enabled.** They're live behind Basic Auth only, and would become public if Basic Auth is dropped.
- **P2-2** **No security headers:** no CSP, no `frame-ancestors`/X-Frame-Options (clickjacking), no Referrer-Policy.
- **P2-3** **Cookies can't be revoked.** Logout only deletes the cookie client-side, and a password reset doesn't invalidate existing cookies (12 h TTL). Deactivation does take effect immediately.
- **P2-4** **No limits on input or rate.** Manager text length, audio upload size (Vercel caps at 4.5 MB, a container would not) and requests per user are all unbounded, so an authenticated user could run up provider cost.
- **P2-5** **AI client can be talked out of its role.** Manager text goes straight into the dialog; "forget your instructions…" can break the persona. This is low harm (training integrity only, since the KB isn't secret) but is worth a guard line in the prompt.
- **P2-12** **Production database credentials on a dev laptop.** `.env.local` holds production Neon credentials (pulled by the Vercel CLI). It's gitignored, but a production credential shouldn't live there.

**Audit and data**
- **P2-6** **Audit detail gaps:**
  - `user.edit` logs the new role/team but not the old values.
  - Not logged: `session.finish`, `scoring.failed`, `auth.login_failed`, `auth.logout`, `team.edit`.
  - The audit log is append-only by convention only, not protected at DB level.
- **P2-9** **Transcript turns lack a unique `(session_id, turn_index)`.** Concurrent requests could duplicate an index; today the UI's busy flag prevents this.

**Performance**
- **P2-7** **Dashboard computes in Python over every session in range.** Fine for a pilot (hundreds of sessions); it will need SQL aggregation later.
- **P2-8** **`latency_ms` measures only the dialog model.** End-to-end voice-turn latency (STT + LLM + TTS + network) isn't measured or shown, so the 2–4 s target can't be verified from data.

**Engineering**
- **P2-10** **No CI.** Tests run only locally.
- **P2-11** **Stale comments and docs.** `models.py` says scoring uses a BackgroundTask; `auth.py` refers to Railway; README setup paths point at the old folder. The local `.venv` points at the old path, and the repo on an iCloud-synced Desktop is too slow to run.
- **P2-13** **Migrations are ad hoc.** `_add_missing_columns` handles only additive changes. A real migration tool (Alembic) should come before any non-additive schema change, such as multi-tenancy.

**UX**
- **P2-14** **Two logins in production.** Users log in twice (Basic Auth pop-up, then app login).
- **P2-15** **Lead's managers table** is sorted by "needs help" but isn't user-sortable or filterable.

### P3 — future SaaS work
- **P3-1** **Multi-tenancy:** there is no organization concept anywhere (see §7).
- **P3-2** **SSO** (OIDC/SAML): there is a clean seam but no implementation (see §8).
- **P3-3** **Transcript retention and deletion tooling:** none exists yet; this depends on the [BANK] policy.
- **P3-4** **Products are created implicitly** by posting a first KB version; there's no product management page.
- **P3-5** **Bank-specific constants in code:** `STT_VOCABULARY` contains "Эсхата Онлайн" and "сомони". These would move into per-organization config.

---

## 5. PRD gap matrix

| PRD section | Status | Notes |
|---|---|---|
| §2 KB is source of truth | **Partial** | Strong in prompts, scoring and version binding; broken by P0-1 (placeholder publish) and P0-2 (self-approval). |
| §3 Roles, server-side RBAC | **Done** | Enforced and tested; compliance dispute access missing (P1-6). |
| §4 Four products | **Partial [BANK]** | 4 products modelled; 1 approved. "Эквайринг" is represented by `merchant_onboarding` (QR/wallet payment acceptance via Эсхата Онлайн). Whether that is the bank's эквайринг product or a separate card-acquiring product is needed is a bank question. |
| §5 12 scenarios with full fields | **Partial** | All fields are supported (profile, hidden needs, objections, emotion, decision criteria, weights, topics, versions). 11 of 12 unpublished (P0-3). No explicit "scenario instructions" field; `learning_goal`, `feedback_hints` and `good_examples` serve that role. |
| §6 AI client behaviour | **Done** | Prompt covers every listed must and must-not; persona-break hardening is P2-5. |
| §7 Session UX | **Partial** | Voice, text fallback and briefing work; timer, states, identity and graceful errors missing (P1-1, P1-3). |
| §8 Scoring | **Done** | Rubric matches; deterministic cap; explainable. Silent-cap edge case P1-2. |
| §9 Results | **Partial** | All data present; presentation and grouping need work (P1-4). |
| §10 Manager workspace | **Partial** | History and repeat exist; progress/overview missing (P1-5). |
| §11 Sales Lead workspace | **Mostly done** | KPIs, trend, skills, products, risks, managers needing help, drill-down. Table sort/filter is P2-15; no separate Team/Reports pages. |
| §12 Training workspace | **Partial** | Editor and versions exist; search, filter, duplicate and a structured editor are missing (P1-8, P1-9). |
| §13 Product workspace | **Partial** | Versioned KB with history; JSON editor, no dependency view (P1-7, P1-8). |
| §14 Compliance workspace | **Weak** | Can approve and read the audit log; no approvals queue, no disputes, no risk-event list (P1-6, P1-7). |
| §15 Admin workspace | **Partial** | User create/edit and team create; no search, team lead/stats or confirmations (P1-9). |
| §16 Auditability | **Mostly done** | Gaps in P2-6. |
| §17–19 Design, states, responsive | **Partial** | Token-based CSS, light/dark, usable on small screens; top-nav prototype look, minimal loading and empty states, raw errors. |
| §20 Security | **Mostly done** | See P1-10 and P2-1 to P2-5, P2-12. |
| §21 Latency | **Mostly done** | Dialog latency is well under target; end-to-end voice latency not measured (P2-8). Scoring has a budget and retry. |
| §22 Retention | **Partial [BANK]** | Audio never stored ✓. Transcripts, scores and audit kept indefinitely; no policy defined. |
| §23 SSO and deployment | **Ready to extend** | See §8. |
| §24 Multi-tenancy | **Not started** | See §7. |
| §25 Testing | **Partial** | 43 access tests + manual gate test; scoring and KB logic untested (P1-11); no CI. |

---

## 6. Security review summary

| Area | Result |
|---|---|
| Backend authorization / IDOR | Every session-scoped route goes through `_load_session` (owner / same-team lead / admin; write = owner only). Admin and content routes use role dependencies. No IDOR found. |
| Team isolation | Lead dashboard team is forced server-side; manager drill-down checks the target's team. Tested. |
| Transcript access | Aggregate roles blocked. Tested. |
| KB and scenario edit permissions | Role-gated and status-gated (only drafts editable). **Separation of duties missing (P0-2).** |
| Admin routes / audit access | Admin-only / admin+compliance. Tested. |
| Secrets | All provider keys server-side via env; none in static files. `.env*` gitignored; no secrets in git history (addendum). |
| Passwords | PBKDF2-SHA256 200k iterations, constant-time compare, minimum 8 characters. |
| Session cookie | HMAC-SHA256-signed, HttpOnly, SameSite=Lax, Secure over HTTPS; app refuses to sign without `SECRET_KEY` on Postgres. Not revocable (P2-3). |
| CSRF | SameSite=Lax cookie + JSON-body endpoints; no cross-site write vector found. |
| XSS | All interpolated text escaped. |
| Brute force | No throttling (P1-10). |
| Exposure | `/docs` enabled (P2-1); no security headers (P2-2). |
| Data sent to third parties | DeepSeek, Deepgram, ElevenLabs, Anthropic **[BANK]** (P0-4). |

---

## 7. Multi-tenancy assessment

**Current coupling to one bank**
- **No organization entity.** `users.username` and `teams.name` are globally unique; products, KBs, scenarios, sessions and the audit log have no owner column.
- **Bank-specific data:** seed content (Банк Эсхата, сомони, Эсхата Онлайн) and `STT_VOCABULARY` in `app/constants.py`.
- **Global rubric** in `seed/rubric.json`.
- **Prompts** are generic ("клиент банка"), which is good.

**Required changes (estimate: medium-large, 1–2 weeks with tests)**
1. Add an `organizations` table and `org_id` foreign keys on `users`, `teams`, `products`, `knowledge_base`, `scenarios`, `scenario_versions`, `sessions` and `audit_log`. Scope uniqueness per org.
2. Put `org_id` on the user and the cookie, and make every query filter by it. The central helpers (`get_current_user`, `_load_session`, `published_kb`, `build_dashboard`, the admin list endpoints) make this tractable, but every query must be reviewed. Isolation tests per org are essential.
3. Make rubric and STT vocabulary per-organization configuration.
4. Adopt Alembic before doing this (P2-13). It's a non-additive migration with backfill to a default org.

**Recommendation:** don't do this before the pilot. Low-risk preparation now:
- keep all new queries going through the existing central helpers;
- move `STT_VOCABULARY` into config;
- adopt Alembic.

---

## 8. SSO and deployment readiness

- **SSO seam:** all identity resolves through `get_current_user()` plus the signed cookie. An OIDC or SAML login route can map an IdP identity to a `User` row and issue the same cookie, with no change to RBAC.
- **Needed for SSO:** `email` / `external_id` / `auth_provider` columns, just-in-time provisioning rules, and role mapping from IdP groups **[BANK]**.
- **Deployment portability:** the app is fully env-configured; it runs as a container (Dockerfile) or on Vercel. On-prem or private cloud needs Postgres plus outbound access to the AI providers. If outbound access is disallowed, the providers must be replaced by self-hosted models behind the same interfaces in `app/providers/base.py`. **[BANK]** decides the hosting model.

---

## 9. Technical debt (not blocking)
- `app/main.py` (682 lines) mixes page routes, the session API and scoring orchestration; the router split was started.
- The ad-hoc migration helper should be replaced with Alembic before the schema grows.
- Dashboard analytics are computed in Python.
- No frontend build or tests. This is fine at the current size, but the role workspaces (Phase 5) will grow `admin.html` beyond what vanilla JS stays maintainable at. Decide on componentization before Phase 4 (see the plan).
- The manual `init_db` step on Vercel deploys is easy to forget. It should become part of the deploy checklist or CI.

---

## 10. Bank decisions required [BANK]
1. **External AI processors:** may conversation data go to DeepSeek, Anthropic, Deepgram and ElevenLabs, and in which regions? This may require replacing DeepSeek.
2. **Approved product materials** for РКО, Зарплатный проект and Кредит; confirmation that `merchant_onboarding` is the "Эквайринг" product.
3. **Who signs off** on product facts (product owner vs compliance) and whether admin may bypass.
4. **Production hosting:** SaaS (Vercel + Neon, US region today), private cloud, or bank infrastructure.
5. **Transcript, score and audit retention** period, and the deletion/export process.
6. **SSO requirement** and IdP (AD FS / Azure AD / Keycloak…).
7. **User provisioning:** who creates accounts, team structure, lead assignment.
8. **Security requirements:** penetration test, IP allow-listing, VPN, logging/SIEM export.
9. **Pilot cohort, success metrics and support contact.**

---

## 11. Recommended implementation order
1. **P0-1, P0-2:** server-side publish guard for placeholder KBs, and four-eyes approval. Small, contained changes in `content.py` and `admin.py`, with tests.
2. **P1-11:** tests for scoring math, cap, KB enforcement, hidden-field and version binding. Locks in correctness before UI work.
3. **P1-1, P1-2:** graceful provider-failure handling (friendly errors, keep the manager's text, safe retry) and an always-explained cap.
4. **P1-10, P2-1, P2-2:** login throttling, hide `/docs`, security headers. Small changes that unblock dropping Basic Auth.
5. **Phase 4 design system:** layout and sidebar navigation, typography, tables, forms, dialogs, and loading/empty/error states. Then migrate pages.
6. **Phase 5 workspaces:**
   - manager overview and progress (P1-5) and results hierarchy (P1-4);
   - compliance approvals queue and disputes (P1-6, P1-7);
   - structured KB and scenario editors (P1-8);
   - admin search, teams and confirmations (P1-9).
7. **P2 hardening** (audit details, rate limits, CI), then the pilot checklist.
8. **In parallel, the bank** supplies P0-3 content and decides P0-4 and §10.

---

## Addendum — git-history secret scan

Searched all commits for Anthropic (`sk-ant-…`), Neon (`npg_…`), ElevenLabs (`sk_…` hex) and `xi-api` patterns. One match: the HTTP header **name** `"xi-api-key"` in `app/providers/elevenlabs_tts.py` (commit `2af07dd`), not a key value. **No secrets found in history.** `.env` and `.env.local` were never committed; only `.env.example` (empty values) is tracked.
