# Pilot Foundation Review

**Date:** 2026-10-05 · **Reviewed commit:** `fbda337` (branch `vercel-deploy`) · **Type:** review only. No application code changed.
**Purpose:** confirm the backend and security foundation carries no unresolved engineering P0 risk into the Phase 4 UI/UX work.

---

## 1. Checkpoints

```
fbda337 phase 3b: harden pilot authentication and HTTP security
7e390f0 phase 3a: harden AI service failure handling
d57d772 phase 2: add pilot-critical regression coverage
507b698 phase 1b: close scoring and content safety gaps
ed9a93a phase 1: harden KB approval and score cap transparency
da4b55d (base) Add light/dark theme switch and training topics for scenarios
```
- **Separate local commits:** one per phase.
- **Working tree:** clean after the Phase 3B commit. This review document and one plan correction (A0-2 marked done) are the only uncommitted changes.
- **Remote:** `vercel-deploy` is 5 commits ahead of `origin`; nothing pushed, merged or deployed.
- **Production still runs pre-Phase-1 code** (last deployed from `e9a0751`). None of Phases 1–3B is live.

## 2. Regression

Run from a clean `git archive` export of `fbda337`, so nothing depends on uncommitted files:

| Run | Result |
|---|---|
| `pytest` | **408 passed** |
| `pytest tests` | **408 passed** |
| all phase files, reversed | 408 passed |
| all phase files, interleaved | 408 passed |

Offline: stub providers, temporary SQLite, no credentials. No test file references a real provider URL. The real-model gate test (`tests/run_gate_test.py`) was **not** run; see the deployment gate.

**Additional read-only checks for this review:**
- **Session cookie over HTTPS:** `HttpOnly; Secure; SameSite=lax; Max-Age=43200`. Over HTTP, `Secure` is omitted, as designed.
- **Schema:** no binary/`LargeBinary` column exists, so no table can hold audio.
- **Audit:** every content, user and team, login, score and dispute action has an `audit()` call.

---

## 3. Pilot invariants

Legend: **P** protected · **PP** partially protected · **NP** not protected · **BD** bank decision required.

### Product / AI safety

| Invariant | Status | Evidence |
|---|---|---|
| KB is the source of truth | **P** | The AI client prompt is built only from the session's bound KB snapshot (`build_client_system_prompt`), and claim checks receive the same snapshot. `test_phase2_version_binding` asserts the prompt and claim checker see exactly the bound facts. |
| Unreviewed KB can't be published | **P** | `kb_review_blockers` + 409 `kb_unreviewed` on approve and publish (`test_phase1`: approve, publish, `draft_note`, no partial transition, no audit row). The developer seed loader can still insert a published KB, but the only seeded one is clean. |
| Scenario publication needs a published, clean KB | **P** | 409 without a published KB; 409 `kb_not_clean` against a dirty legacy KB (`test_phase1`). |
| Unsupported claims can't silently become approved | **P** | Unsupported → `unapproved`, which triggers the cap (`test_phase1` API tests, `test_phase1b`). The verdict itself comes from the LLM claim checker; engineering can't guarantee the model recognises every invented condition. The real-model gate fixtures cover a mis-selling dialogue. |
| Unknown claim verdicts fail closed | **P** | Provider normalisation and retry, plus a backend `fail_closed_verdict` before persistence (`test_phase1b`, provider tested separately from the backend boundary). |
| Mis-selling triggers the 60 cap | **P** | Deterministic `compute_total` / `has_critical_error`; 100→60, 74→60, 42→42 (`test_phase1`). |
| Malformed scorer output can't inflate the score | **P** | Provider rejects duplicate, unknown or missing criteria with a retry; `compute_total` counts each criterion once (`test_phase1b`, 28 bug-specific tests that fail on old code). |
| Scoring remains explainable | **P** | Per-criterion reason and quote, claim verdicts with reasons, deterministic `cap_reason` (`test_phase1`, `test_phase2_scoring` persistence). The *quality* of explanations depends on the model; the results page presentation is Phase 5. |

### Version integrity

| Invariant | Status | Evidence |
|---|---|---|
| Session binds scenario version | **P** | `sessions.scenario_version` set at start (`test_phase2_version_binding`). |
| Session binds KB version | **P** | `sessions.kb_version` set at start; only the *published* KB, never newer approved or draft versions. |
| A newer publish can't change a running session | **P** | v2 scenario and KB 2.0.0 published mid-session; the session stays on v1 / 1.0.0. |
| Client simulation uses the bound versions | **P** | Prompt contains v1 pain, difficulty and facts, not v2. |
| Scoring uses the bound versions | **P** | Scorer receives v1 goal, hints and weights (total 100 vs 0 under v2); claim checker receives the KB 1.0.0 facts and forbidden list. |
| Result keeps the bound versions | **P** | `/score` and `/transcript` report v1 / 1.0.0 when re-read after v2 went live. |

### Privacy / authorization

| Invariant | Status | Evidence |
|---|---|---|
| Manager can't access another manager's session | **P** | 8 callers × 8 routes (`test_phase2_session_access`); refused writes leave no trace. |
| Sales lead access stays team-scoped | **P** | Same-team lead can read, other-team lead gets 403; drill-down follows the team; dashboard forces the lead's team. |
| Content roles don't get individual transcripts | **P** | Training, product and compliance get 403 on transcript, score and audio. *Note:* the PRD wants compliance to review **disputed** results; that's not possible today (P1, see §5). |
| Hidden client info never reaches managers | **P** | Sentinel values in all 12 hidden fields, objections, hidden variants and coaching absent from every manager response (`test_phase2_hidden_fields`). |
| Hidden info still reaches the AI client | **P** | Every hidden value in the AI client prompt on every turn; coaching material reaches the scorer. |
| Audio is never persisted | **P** | Audio is deleted after STT; the DB-file scan finds no audio marker (`test_phase3a`); no binary column exists in the schema. |
| Draft content isn't exposed to managers | **P** | `/kb/*` and `/admin/*` give 403 (`test_phase2_content_authz`); draft-only products hidden from `/products` (`test_phase1b`). |

### Reliability

| Invariant | Status | Evidence |
|---|---|---|
| Text AI failure leaves no partial transcript | **P** | 502 `dialog_unavailable`, no turn stored, retry adds exactly one pair (`test_phase3a`). |
| STT failure leaves no transcript state | **P** | 502 `stt_unavailable`, AI client not called, transcript unchanged. |
| STT ok + dialog failure keeps recoverable text | **P** | `manager_text` returned, nothing stored, resend gives one pair. |
| TTS failure doesn't roll back dialogue | **P** | 200 with committed pair and `audio_error`. |
| TTS replay can't duplicate turns | **P** | Replay is read-only; transcript unchanged before and after recovery. |
| Scoring failure creates no fake result | **P** | `finish_error` returns only `{status, code, detail}`; retry re-scores without duplicated rows (`test_phase3a`, `test_phase2_scoring`). |
| Raw provider errors don't reach the browser | **P** | Marker sweep over failing responses, transcript, score, history, audit and dashboard for owner, lead and admin. The frontend reconciliation logic was checked by code inspection and served-asset tests only; **browser QA pending.** |

### Security

| Invariant | Status | Evidence |
|---|---|---|
| Password hashing fits the pilot | **PP** | PBKDF2-HMAC-SHA256, random 16-byte salt, constant-time compare. **200,000 iterations, below OWASP's current 600,000** for PBKDF2-SHA256. Acceptable for an internal pilot behind Basic Auth with throttling; raising it is a P2 (login latency on serverless should be measured first). The final requirement is part of B-13. |
| Login throttling is active and DB-backed | **P** | `login_attempts`, 5 per 15 min per (username, IP) (`test_phase3b`). In production it's **per username only** until `CLIENT_IP_HEADER=x-real-ip` is set (deployment gate). |
| Username-enumeration protection | **P** | Identical 401 and 429 for unknown and existing usernames; dummy PBKDF2 equalises timing. Remaining: the admin "create user" API returns 409 for an existing login (admin-only, by design). |
| Security headers fit the app | **PP** | CSP derived from the page sources and verified by test (no external resources, required directives). **Not yet checked in a real browser** (microphone, audio, charts, dialogs). `'unsafe-inline'` remains. |
| API docs disabled in production | **P** | 404 by default when the DB isn't SQLite; production uses Postgres (`test_phase3b`). |
| Unexpected exceptions are sanitised | **P** | Generic 500 with `request_id`; no SQL, credentials, exception class or traceback in the response (`test_phase3b`). |
| Diagnostics sanitised before persistence | **P** | `redact()` on `scoring_error` (`test_phase3b`). Pre-existing production rows weren't rewritten. |
| Request IDs for support | **P** | Server-generated `X-Request-ID`, in 5xx/429 bodies, log lines and the UI error text. |
| No secrets in app logs or audit events (tested) | **P** | `app` logger redaction filter; audit never stores passwords or unknown usernames (`test_phase3b`). Framework (uvicorn/Vercel) logs aren't filtered. |
| Session cookie properties kept | **P** | Verified for this review: `HttpOnly; Secure (HTTPS); SameSite=lax; 12 h`. Still not revocable on logout or password reset (accepted limitation). |

### Auditability

| Invariant | Status | Evidence |
|---|---|---|
| Content lifecycle actions are audited | **P** | `scenario.create`, `scenario.edit_draft`, `scenario.new_version`, `scenario.status`, `kb.new_version`, `kb.edit_draft`, `kb.status` (all with from→to), committed in the same transaction. A refused transition writes nothing (`test_phase1`). |
| Login security events are audited | **P** | `auth.login_failed`, `auth.login_throttled` (once), `auth.login` with `previous_failures` (`test_phase3b`). |
| Results keep scenario and KB versions | **P** | `sessions` columns, `session.scored` audit details (`test_phase2_scoring`). |
| Critical errors and claim verdicts persist | **P** | Re-read identically by owner, lead and admin (`test_phase2_scoring`, `test_phase1b`). |
| Failure and retry keep the audit trail | **PP** | Nothing is deleted or overwritten in `audit_log`, and a retried score is audited once on success. **Failures themselves aren't audited** (`scoring.failed`, `session.finish` missing; plan A2-1). Old→new values on `user.edit` aren't recorded (A2-1). |

**Summary (43 invariants):**
- **40 protected.**
- **3 partially protected:** password-hash cost, header and CSP browser QA, and auditing of failure events.
- **0 not protected.**
- **Note within a protected row:** compliance can't yet review disputed results (P1, depends on B-2).

Bank decisions are listed in §4B.

---

## 4. Remaining P0 items

Sources: `PILOT_READINESS_AUDIT.md`, `PILOT_READINESS_PLAN.md`, Phase 1–3B records.

### A. Engineering P0
**None outstanding.**

| Original P0 | Status |
|---|---|
| A0-1 unreviewed-KB guard | Done (Phase 1) |
| A0-2 safety-net tests | Done (Phases 1, 1b, 2, 3A, 3B: 408 tests) |
| A0-3 transcript/screen consistency | Done (Phase 3A) |
| A0-4 no raw provider errors | Done (Phase 3A) |
| A0-5 explained score cap | Done (Phase 1) |
| A0-6 login throttling | Done (Phase 3B) |
| Bugs found during Phase 2 | Fixed (Phase 1b) |

**Operational items, not engineering P0 and not blocking Phase 4, but must happen before the pilot:**
- deploying Phases 1–3B with the `init_db` step;
- browser QA;
- one real-model gate run.

These are in the deployment gate (§7).

### B. Bank-decision P0
| ID | Decision |
|---|---|
| B-1 | Four-eyes rule: may an editor approve their own change; may an admin act alone? (Today: allowed; the policy hook is ready.) |
| B-2 | Who approves what (product facts, scenarios), and whether compliance may open disputed sessions |
| B-3 | Approval to send conversation data to Anthropic, Deepgram, ElevenLabs |
| B-4 | DeepSeek specifically (dialog model), and an approved alternative if refused |
| B-5 | Allowed data-processing regions (Neon and Vercel functions are currently US-East) |
| B-6 | Hosting model (current SaaS on Vercel + Neon, private cloud, or bank infrastructure) |
| B-9 | Retention of transcripts, scores, audit log and stored scoring diagnostics |
| B-13 | Production security requirements (password policy and hash cost, session TTL, MFA) |
| B-14 | Whether the Basic Auth outer gate stays during the pilot (it currently forces a double login) |

Required before production but not P0 for the pilot design: B-7 SSO, B-8 provisioning, B-10 penetration test, B-11 network restrictions, B-12 SIEM. None of these are assumed by engineering.

### C. Bank-content P0
| ID | Content |
|---|---|
| C-1 | Approved РКО facts, arguments, objection responses, disclaimers |
| C-2 / C-3 | Approved Эквайринг facts, and confirmation whether `merchant_onboarding` *is* the bank's Эквайринг product or card acquiring is separate |
| C-4 | Approved Зарплатный проект facts |
| C-5 | Approved Кредит для бизнеса facts |
| C-6 | Approved compliance restrictions (forbidden formulations, critical errors) per product |
| C-7 | Review and approval of the 11 draft scenarios |

Today 1 of 4 products and 1 of 12 scenarios are approved. Engineering won't invent any of this content: the Phase 1 guard **technically blocks** publishing the developer placeholders.

---

## 5. Remaining P1 items

| ID | Item | Classification | Note |
|---|---|---|---|
| A1-1 | Design system and app shell | **Part of Phase 4+** (Phase 4) | Also the place to move inline scripts into modules and drop `'unsafe-inline'` from `script-src` |
| A1-2 | Live training screen | **Part of Phase 4+** (Phase 5) | Must keep Phase 3A's transcript reconciliation |
| A1-3 | Results page hierarchy | **Part of Phase 4+** (Phase 5) | `cap_reason` already provided |
| A1-4 | Manager overview, progress, history | **Part of Phase 4+** (Phase 5) | Needs new `/me/progress` (own data only) |
| A1-5 | Compliance access to disputed results | **Before pilot launch** | The access rule depends on B-2; implement only after confirmation |
| A1-6 | Approvals queue, KB → scenarios view, archive warnings | **Before pilot launch** | Needed for the bank team to process C-1…C-7 efficiently and safely |
| A1-7 | Structured KB and scenario editors (with JSON view) | **Before pilot launch** | Required if bank staff enter C-1…C-7 themselves. If engineering enters content from bank documents, it can slip to "during pilot" — the bank decides who enters content |
| A1-8 | Admin users and teams, confirmation dialogs | **Before pilot launch** | Confirmations for role change, deactivation, publish and archive |
| A1-10 | Lead team table and performance views | **Part of Phase 4+** (Phase 6) | Current dashboard is usable meanwhile |
| A1-11 | Duration hint | **Optional during pilot** | Needs C-8 values from the bank |
| A1-12 | End-to-end voice latency measurement | **Before pilot launch** | Needed to verify the 2–4 s target with real providers |

**Before UI:** no P1 item has to precede Phase 4. The error-code contract (`code`, `detail`, `request_id`, `manager_text`, `audio_error`, `cap_reason`) that the UI will consume is stable and tested.

---

## 6. Accepted security limitations (Phase 3B)

| Limitation | Risk | Blocks Phase 4? |
|---|---|---|
| CSP allows inline scripts and styles (`'unsafe-inline'`) | XSS defence relies on output escaping (`esc()`, verified in the audit) rather than CSP | **No.** Phase 4 is the natural place to remove inline scripts. Recommend making `script-src 'self'` an exit criterion of Phase 4. |
| Throttle is per (username, IP), not global per username | Slow distributed guessing across many IPs isn't capped | No. Mitigated by Basic Auth (if kept) and 5/15 min per IP; add a global cap only if B-13 asks. |
| Existing login cookies aren't revoked by logout or password reset | A stolen cookie stays valid up to 12 h | No. Deactivation and role change take effect immediately (`test_phase2_auth`); A2-3 remains P2. |
| Framework-level logs (uvicorn/Vercel) don't use app redaction | An unhandled exception's message could reach platform logs unredacted | No. Only server-side, access-controlled logs. Keep log level at INFO or above (DEBUG makes DB drivers log SQL parameters). |
| API-docs default uses "DB is SQLite" as the local-dev signal; `API_DOCS` overrides | A non-SQLite dev setup has docs off unless `API_DOCS=true`; a SQLite production would expose docs | No. Production is Postgres. Never run production on SQLite (it also has no persistent disk on Vercel). |
| Header and CSP behaviour not yet verified in a real browser | A directive could block something the tests didn't anticipate | No for UI work; **yes for deployment**: deployment gate items 6–8. |
| PBKDF2 at 200,000 iterations (below current OWASP guidance) | Faster offline cracking if password hashes leak | No. P2, pending B-13; measure serverless login latency before raising. |

---

## 7. Deployment gate (pre-production checklist)

Not executed. **Production currently runs pre-Phase-1 code;** this checklist applies when Phases 1–3B (+ any Phase 4 work) are deployed.

1. ☐ **Backup:** confirm Neon point-in-time restore / branch is available for the production DB, and note the current Vercel production deployment ID for rollback.
2. ☐ **Schema:** run `scripts/init_db.py` against production **before** deploying the new code (creates `login_attempts`; additive and idempotent). Verify the table and its 2 indexes exist.
3. ☐ **Env:** `CLIENT_IP_HEADER=x-real-ip` set for production (and preview if used).
4. ☐ **Logging:** production log level INFO or above (never DEBUG).
5. ☐ **Secrets:** `SECRET_KEY` set (long, random); the four provider keys valid (Anthropic key verified with a real scoring run); `DATABASE_URL` pooled + SSL; no unused or demo secrets; `SEED_DEMO_USERS` unset.
6. ☐ **API docs:** `/docs`, `/redoc`, `/openapi.json` return 404 in production; `API_DOCS` not set to true.
7. ☐ **HTTPS and headers:** production responses carry CSP, nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy, X-Request-ID, and Vercel's HSTS; no CSP violations in the browser console on every page.
8. ☐ **Microphone:** permission prompt and recording work in Chrome, Edge and Safari (desktop), with `Permissions-Policy: microphone=(self)`.
9. ☐ **Audio playback:** voice-turn base64 audio and text-turn audio replay both play; TTS failure shows the "озвучка недоступна" note.
10. ☐ **Login and throttling smoke test:** correct login works; 5 wrong attempts for a test account → 429 with Retry-After; wait or clear → login works; `auth.login_failed` / `auth.login_throttled` visible in the audit log.
11. ☐ **Manager training smoke test:** select scenario → voice and text turns → simulated provider failure shows a friendly error and the text is kept → finish.
12. ☐ **Scoring smoke test:** one real-model scoring run (and the gate test `tests/run_gate_test.py` once, costing a small amount of API credit) to confirm the Phase 1b validation accepts real Claude output; the cap and `cap_reason` display correctly.
13. ☐ **Transcript and version binding:** the result shows the expected scenario and KB versions; the transcript matches what was said.
14. ☐ **No audio persistence:** confirm no audio objects in DB or storage after a voice session (schema has no binary columns; spot-check).
15. ☐ **Rollback plan confirmed:** code rollback by promoting the previous Vercel deployment (the `login_attempts` table can stay); DB restore from the step-1 backup only if data was affected.
16. ☐ **Basic Auth:** decision B-14 applied (keep, with credentials shared via the agreed channel, or remove now that throttling exists).

---

## 8. Recommendation

# PHASE 4 GO

**Reason:**
- **No engineering P0 is outstanding.** Every engineering P0 in the audit and plan (A0-1…A0-6, plus the three bugs found in Phase 2) is implemented and covered by 408 offline tests that pass in any order.
- **Every invariant on the list is protected or partially protected; none is unprotected.** The 3 partial ones are:
  - the password-hash cost (P2, bank requirement);
  - browser verification of headers (a deployment-gate item);
  - auditing of failure events (P2).

  Separately, compliance can't yet review disputed results (P1, bank decision B-2).
- **None of these is changed or made riskier by UI work.**
- **The contract the new UI depends on is stable and tested:** error codes, `request_id`, `manager_text`, `audio_error`, `cap_reason`, version fields and RBAC.

**What GO does not mean:**
- not ready for production deployment (§7 is open, and Phases 1–3B aren't deployed);
- bank decisions B-1…B-6, B-9, B-13, B-14 are not made;
- approved content C-1…C-7 doesn't exist;
- the pilot isn't approved.

Those are separate gates.

**Conditions recommended for Phase 4:**
- Keep the 408-test suite green.
- Preserve the Phase 3A transcript-reconciliation behaviour in the new training screen.
- Move inline scripts into modules so `script-src 'unsafe-inline'` can be dropped as a Phase 4 exit criterion.
- Run the browser QA items 7–9 on the new shell.
