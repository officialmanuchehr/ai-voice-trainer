# Phase 9 — Pilot QA and launch readiness

**Date:** 2026-10-06 · **Base:** `649a6f5` (Phase 8) · **Status:** engineering fixes and QA **uncommitted**; not pushed or deployed; **no paid provider calls made**.

**Question:** can 10–20 real Bank Eskhata employees safely use this system in a controlled pilot?

**Answer:** the **engineering** is ready for a real-provider staging gate. **Bank and pilot readiness is BLOCKED** by provider approval, retention and content (see the end of this document).

Companion documents:
- `DEPLOYMENT_CHECKLIST.md`
- `BANK_PILOT_DECISIONS.md`
- `PILOT_CONTENT_GATE.md`
- `PILOT_ACCEPTANCE_MATRIX.md`
- `PILOT_RUNBOOK.md`

The feature set is **frozen**. Phase 9 changed code only for the engineering P1 items below.

## 1. Launch-blocker audit
| Item | Finding | Class | Action |
|---|---|---|---|
| A2-2 input limits | No ceilings on turn text, audio size, turns per session, login or admin fields, or content documents; dispute text silently truncated | **Must fix** | Fixed (§2) |
| A2-4 persona guard | Prompt had no rule against AI self-identification or prompt leakage; no response guard | **Must fix** | Fixed (§3) |
| A2-6 CI | None | **Must fix** | Added (§4) |
| Stub providers in production | Providers default to `stub`; a missing env var would give pilot users **fake replies and scores** without any signal | **Must fix** (small) | Startup warning plus a checklist check |
| A2-11 local production credentials | `.env.local` (a Vercel CLI pull) on the developer machine holds production DB and provider credentials; the app never reads it; git-ignored, never committed | Pilot QA / process | Checklist item: delete or secure after deployment. Not touched (not authorised) |
| Preview shares the production DB | `DATABASE_URL` is set for **Production and Preview**: any preview deployment would run on pilot data | **Must fix (config)** | Checklist: give Preview its own database or disable preview deployments |
| `CLIENT_IP_HEADER` unset | Login throttling keys on the direct peer address; behind Vercel this should be `x-real-ip` | **Must fix (config)** | Checklist |
| Active-session reload | Re-tested: no corruption, no duplicated or lost turns (§9) | Pilot QA | Runbook instruction |
| Production env, secrets | See §5 | PASS | — |
| DB init / migrations | Idempotent create + additive columns + insert-only seed; no columns added since Phase 4 | PASS for the pilot | §6 |
| Provider timeouts | 30 s httpx timeout (Deepgram, DeepSeek, ElevenLabs); scoring streams, 270 s budget under Vercel's 300 s; schema-checked retries (3); failures are safe 502s with request ids | PASS (to be measured in the gate) | — |
| Logging / request ids / errors | Redacting log filter; server-generated `X-Request-ID`; safe 500 bodies | PASS | Smoke-tested |
| Cookies / CSP / headers | HttpOnly, SameSite=Lax, Secure on HTTPS; strict CSP; nosniff, DENY, Referrer-Policy, Permissions-Policy; HSTS from Vercel (verified live in Phase 3B) | PASS | Smoke-tested |
| Transcript retention | Stored indefinitely; no deletion job | Bank decision (B-9) | — |
| Audio non-storage | Confirmed (§7) | PASS | — |
| Version / KB binding | Confirmed end to end (§8) | PASS | Acceptance test |
| Backup / restore | Procedure defined; restore drill **not performed** (no local Postgres tooling; production not touched) | Pilot QA | §6, checklist |
| Rollback | Vercel "promote previous deployment"; schema is additive, so older code runs on the newer schema | Pilot QA (rehearse) | Checklist |
| Indexes | Only `login_attempts` has explicit indexes; FK lookups are unindexed. Fine at pilot volume | Post-pilot (A2-8) | — |
| Per-user turn rate | Not limited; bounded per session by the turn ceiling | Post-pilot | — |

## 2. A2-2 input limits (`app/limits.py`)
These are technical ceilings for abuse and stability, **not bank policy**. All are far above normal use. They are enforced on the server with a safe 422 or 413 (Russian message, no framework text).

| Input | Ceiling |
|---|---|
| Request body (declared length) | 6 MB → 413 JSON (Vercel itself stops at ~4.5 MB) |
| Push-to-talk audio | 4 MB → 413, **before** the STT call (≈1 min of Opus is < 1 MB) |
| Manager reply (typed or recognised) | 2,000 chars |
| Manager turns per session | 60 (the dialog prompt grows each turn); the session can still be finished |
| Dispute comment | 2,000 chars (now refused instead of silently truncated) |
| Login username / password | 100 / 256 chars |
| Admin: username / full name / password / team name | 100 / 200 / 256 / 200 |
| KB version label / version comment | 40 / 2,000 |
| Scenario document / KB document | 100 KB / 300 KB serialized (the seed KB is ~6 KB) |

The frontend mirrors the 2,000-character limits as `maxlength` (convenience only). Boundary tests sit at exactly the limit and one over.

## 3. A2-4 persona-break guard (`app/persona_guard.py`)
- **Prompt:** three explicit rules were added: never call yourself an AI, model or bot; never mention or quote the profile, instructions or fact list; never step out of role to evaluate or coach the manager.
- **Deterministic reply guard** (no model call). It replaces a reply only on **unambiguous** breaks:
  - AI self-reference ("я — языковая модель", "as an AI");
  - prompt headings or profile keys (`ТВОЙ ПРОФИЛЬ`, `hidden_need`), "скрытая потребность";
  - talk about the system prompt or instructions; "я играю роль клиента";
  - evaluator voice ("менеджеру следует…", "правильный ответ был…").
- **What happens on a match:** the reply becomes a neutral in-character line. A warning is logged with the pattern name and session id only, never the text. It covers text and voice turns.
- **False-positive check:** natural client speech is untouched, e.g. "Я не бот, я владелец…", "Скрытых платежей точно нет?", "Я ассистент бухгалтера…" (tested).
- **Trade-off:** narrow patterns can miss a paraphrased break. Free-form leaks (e.g. the client volunteering its hidden need too early) remain a prompt-quality question for the real-provider gate.

## 4. A2-6 CI (`.github/workflows/tests.yml`)
- **When:** on every push and pull request.
- **What it runs:** Python 3.12, `pip install -r requirements-dev.txt`, Node 20 (so the JS checks execute), `python -m pytest -q`. Stub providers, temporary SQLite, read-only permissions.
- **What it doesn't do:** use secrets or deploy anything.
- **Verified locally** with a clean Python 3.12 environment built exactly as the workflow does: **730 passed**.
- **Not yet run on GitHub:** the workflow runs once the branch is pushed, which is not done.

## 5. Production configuration (names only; values never displayed)
| Check | Status |
|---|---|
| No secrets committed (full history scan; test fixtures are synthetic) | PASS |
| Provider keys from env (`DEEPGRAM_API_KEY`, `DEEPSEEK_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ANTHROPIC_API_KEY`) | PASS (set in Production) |
| Provider modes (`STT_PROVIDER`, `DIALOG_PROVIDER`, `SCORING_PROVIDER`, `TTS_PROVIDER`) | Set in Production; **values must be verified** non-stub at deploy (startup warning added) |
| `DATABASE_URL` from env; no default credentials on Postgres | PASS, but **FAIL: shared with Preview** |
| `SECRET_KEY` production-controlled; the app refuses to sign cookies on Postgres without it | PASS |
| `SEED_DEMO_USERS` (known-password demo accounts) | PASS: not set in Production |
| `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` | Set; only creates the admin if missing |
| `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD` outer gate | Set (B-14 decides whether it stays) |
| `AUTO_INIT_DB` | Set in Production; **must be `false` on Vercel** (verify value) |
| `CLIENT_IP_HEADER` | **FAIL: not set** (should be `x-real-ip` on Vercel) |
| `API_DOCS` | PASS: unset, so off on Postgres |
| Logs | PASS: redaction of configured secret values, bearer tokens, key shapes, DB URL passwords and the session cookie |
| Frontend | PASS: receives no server or provider secrets (only `/auth/me` fields) |

## 6. Database, deployment, backup and rollback
- **Startup path:** Vercel runs `api/index.py`, which loads `app.main`. With `AUTO_INIT_DB=false`, schema and seed are applied by `scripts/init_db.py` run once per deploy.
- **Schema management:** `create_all` (creates missing tables only) plus `_add_missing_columns` (additive `ALTER TABLE ADD COLUMN`, checked via the inspector; no column was added in Phases 5–9).
  - **Seed:** insert-only; never updates or deletes; demo users only when `SEED_DEMO_USERS=true`.
  - **Re-running:** safe and non-destructive.
  - **Assessment:** sufficient for a controlled pilot **with no schema changes during the pilot**. Alembic stays post-pilot (A2-7).
- **Backup (Neon Postgres):** what to back up is the whole database: users, teams, content versions, sessions, transcripts, scores, claim checks, feedback, audit log, login attempts.
  - **Who:** the deployment operator (role, not a named person).
  - **When:** immediately before the pilot deploy and before any content or schema operation, then on the agreed schedule (B-9).
  - **How:** `pg_dump --format=custom "$DATABASE_URL_UNPOOLED" > pilot-YYYYMMDD.dump`, stored encrypted outside the developer laptop. Additionally, rely on Neon's point-in-time restore window and check the window configured for the project plan.
  - **Restore verification:** restore into a **scratch** database or Neon branch, never production (`pg_restore --no-owner -d "$SCRATCH_URL" pilot.dump`); run `scripts/init_db.py` against it (no-op expected); log in as admin; compare row counts of sessions, scores and audit log.
  - **Data loss:** everything written after the backup point (sessions, transcripts, scores, audit events, content edits).
  - **Not performed in Phase 9:** no Postgres tooling locally, and a production-adjacent restore was not authorised. Listed as a Pilot QA gate.
- **Rollback:** promote the previous Vercel deployment. Because the schema is additive, the previous code runs on the newer schema. Data rollback means restore from backup (above).

## 7. Stored data and privacy inventory
| Data | Stored? | Where |
|---|---|---|
| **Audio** | **No.** Recordings are read into memory, sent to STT and discarded (`del`); TTS audio is returned base64 and re-synthesised on replay. No file writes anywhere in `app/` (only the seed file is read), no binary columns, no audio or text in logs | — |
| Transcripts (text) | Yes | `transcript_turns` (+ dialog latency) |
| Scores, breakdown, critical errors, `cap_reason` inputs | Yes | `scores` |
| Evaluator feedback | Yes | `feedback` |
| Claim checks (claim text, verdict, reason) | Yes | `claim_checks` |
| Scenario version / KB version / generated client profile per session | Yes | `sessions` |
| User identity (username, full name, role, team, password hash) | Yes | `users` |
| Audit events (no passwords, transcripts or content bodies) | Yes | `audit_log` |
| Login attempts (hashed key; IP in failed-login audit details) | Yes | `login_attempts`, `audit_log` |
| Disputes (comment, time) | Yes | `scores` |

Retention: indefinite today. **B-9** decides.

## 8. External-provider data flows (facts, not legal claims)
| Provider | Called on | Data sent | Never sent |
|---|---|---|---|
| **Deepgram** (`api.deepgram.com/v1/listen`, nova-3) | Each voice turn | The manager's audio recording; language `ru`; product vocabulary key terms | Names, transcript history |
| **DeepSeek** (`api.deepseek.com`, `deepseek-chat`) | Each turn | System prompt: the generated client profile (**incl. hidden needs and objections**), approved KB fact texts and objection triggers, difficulty rules; **the full conversation so far** | User names, ids, scores |
| **ElevenLabs** (`api.elevenlabs.io`, `eleven_multilingual_v2`) | Each AI reply (and on replay) | The AI client's reply text; voice id | Manager speech or text |
| **Anthropic** (Claude Sonnet 5) | Once per finished session (claim check + scoring; up to 3 attempts each on invalid output) | The full transcript; KB facts, arguments, approved objection responses and forbidden formulations; rubric; claim verdicts | User names, ids |

The transcript may contain whatever a manager says, including client or personal data if they choose to say it. Provider approval, regions and retention at each provider are bank decisions B-3, B-4 and B-5.

## 9. Acceptance tests (`tests/test_phase9_acceptance.py`, 66)
- **Version binding (E2E):**
  - **Setup:** a session on scenario v1 plus KB 1.0.0; KB 1.1.0 and scenario v2 (other product, other difficulty) published **mid-session**.
  - **Bound content:** the next dialog prompt and the claim-check KB still contain only the 1.0.0 fact.
  - **History and analytics:** `/me/sessions`, `/me/progress` products, the lead drill-down, and team product analytics all report v1, KB 1.0.0, product A, "easy".
  - **New sessions:** bind to v2.
  - **Result:** PASS.
- **Mis-selling (E2E), for `unapproved`, `forbidden` and an unknown verdict:**
  - **Setup:** an evaluator returns 95 everywhere and omits the critical error.
  - **Result:** the stored total is 60; `cap_reason` cites the claim; the unknown verdict is stored fail-closed; history, progress and team analytics all use 60. PASS.
- **KB safety:**
  - an unreviewed KB is refused (`kb_unreviewed`);
  - a scenario on a product without a published KB can't be published;
  - after explicit review: approve, publish, the scenario publishes, and the session binds 1.0.0;
  - a later KB 2.0.0 doesn't rewrite it.
  - PASS.
- **RBAC matrix:** 17 read resources × 6 roles plus dispute and write actions. **No unexpected ALLOW.** `/me/sessions` answers 200 for every signed-in role but returns only the caller's own sessions (empty for product and compliance); tested.
- **Security smoke** (an engineering smoke test, **not a penetration test**; B-10 decides pen-test requirements):
  - headers on pages and the API; cookie flags on HTTPS;
  - malformed JSON and wrong types give 422 without traceback; unknown ids give 404; unauthenticated gives 401; oversized gives 413 JSON with request id;
  - escaping and stored-attribute-injection suites still green (earlier phases); IDOR covered by the matrix; throttling covered by Phase 3B tests.
- **Active-session reload:**
  - a "reload" mid-session leaves the first session `active` with its committed turns intact;
  - a new session is independent;
  - nothing is duplicated, lost or re-bound;
  - the abandoned session can still be finished and scored.
  - **Assessment:** no data risk. It is a usability limitation and goes in the runbook as a pilot instruction; resume stays post-pilot.
- **Edge case noted:** if the network drops **after** the server committed a turn and the manager re-sends it, the line appears twice. That's a faithful record, not corruption.

## 10. Browser and device status
| Browser | Status |
|---|---|
| Chrome desktop (headless, fake mic) | **Tested in Phase 9:** six-role sweep (all nav destinations; CSP, JS, leaks, overflow) and the full voice training journey (voice and text turns, claim links, scoring failure and retry, keyboard push-to-talk): **pass** |
| Edge desktop | **NOT TESTED** |
| Safari desktop | **NOT TESTED** |
| Real microphone, speakers, real STT/TTS | **NOT TESTED** (needs the real-provider gate) |

The manual device matrix is in `PILOT_ACCEPTANCE_MATRIX.md`.

## 11. Real-provider gate (plan; **requires explicit approval before execution**)
- **Environment:** a staging deployment with its **own** Neon database or branch (never pilot data) and real provider keys.
  - Test users and content are created there only, with synthetic content and no real customer data.
  - Logs are inspected via Vercel function logs (redacted); results recorded by request id.
- **G1 — components (scripted, no browser):** about 12–17 calls:

  | Run | Calls | Proves |
  |---|---|---|
  | Deepgram | 3 short Russian synthetic recordings (≈5–10 s each; ≈0.5 min audio) | Recognition and vocabulary |
  | DeepSeek | 3 replies on a synthetic scenario | Persona; no persona-guard trips |
  | ElevenLabs | 3 replies (≈150 chars each) | Russian voice |
  | Anthropic | 2 full scorings (one clean, one with a scripted unapproved claim), each = claim check + score, ≤3 attempts on invalid output, so 4–12 calls | Schema validity, cap on the real model |
- **G2 — one complete real voice session in Chrome:** about 8 manager turns, i.e. ≈8 STT + 8 DeepSeek + 8 TTS + 2–6 Anthropic calls; the result page, history and progress are checked.
- **Totals:** about 11 Deepgram, 11 DeepSeek, 11 ElevenLabs, 6–18 Anthropic calls; about 30–45 minutes.
- **Usage, not cost:** ≈2 min of audio; DeepSeek ≈30–40k input tokens (the prompt grows with history; ≤300 output tokens per reply); ElevenLabs ≈2–3k characters; Anthropic ≈10k input tokens and up to 16k output tokens (incl. thinking) per call.
  - Prices aren't quoted because they depend on the bank's or the account's plans.
- **Existing tool:** `tests/run_gate_test.py` (manual, real Claude) can be reused for the scoring part.

## 12. Latency plan (to be measured in G1/G2; no values invented)
| Measure | How |
|---|---|
| STT | Timed around `transcribe` in a G1 script; in G2 from server log timestamps per request id |
| Dialog generation | Already stored per AI turn (`transcript_turns.latency_ms`); dashboard KPI |
| TTS | Timed around `synthesize` in G1; replay endpoint timing in G2 |
| Total response | Browser: release of push-to-talk → audio starts (G2, ≥8 samples; median and max) |
| Scoring | `finish` → result shown (G2; plus the 270 s budget) |

Per-stage latency on the dashboard (A1-12) stays post-pilot.

## 13. Tests
- **Added:** `test_phase9_acceptance.py` (66).
- **Total:** **730 passed** (baseline 664), on Python 3.14 and on a clean Python 3.12 (the CI version).
- **Unchanged areas:** six-role and voice-journey Chrome scripts re-run clean.

## 14. Readiness verdict
- **Engineering readiness: READY** for the real-provider staging gate. There is no known engineering P0. P1 code items are fixed; three configuration actions remain in `DEPLOYMENT_CHECKLIST.md`.
- **Bank and pilot readiness: BLOCKED.** Provider approval (B-3/B-4/B-5), hosting (B-6), retention (B-9), security and network requirements (B-10/B-11/B-13), and bank content (C-1…C-9, incl. C-9) are open. The real-provider gate hasn't run.
- **Overall: NO-GO today.** It becomes **CONDITIONAL GO** when the "must decide before pilot" items in `BANK_PILOT_DECISIONS.md` are decided, pilot content is approved (`PILOT_CONTENT_GATE.md`), the config actions are done, and G1/G2 pass.
