# Phase 1 — Safety and Correctness: implementation record

**Date:** 2026-10-05 · **Base commit:** `da4b55d` · **Scope approved:** A0-1, A0-5, A1-0 from `PILOT_READINESS_PLAN.md`
**Git:** changes are local and uncommitted; nothing pushed or merged.

## Changes made

### A0-1 — Unreviewed KB content can't become approved or published
- **New `kb_review_blockers(data)`** in `app/content.py` lists:
  - a top-level `draft_note`;
  - every entry with `needs_review: true` in `approved_facts`, `approved_arguments`, `objections` and `disclaimers`.
- **`POST /admin/kb/{product}/versions/{v}/status`:** for target `approved` or `published`, any blocker returns **409** with this body:
  ```json
  {"detail": "<Russian message listing the ids>", "code": "kb_unreviewed",
   "unreviewed": [{"section": "draft_note"}, {"section": "approved_facts", "id": "fact_rko_account"}, ...]}
  ```
  The response is returned before any change, so the status is untouched and no audit row is written.
- **Order of checks:**
  1. Lifecycle graph (400).
  2. Role (403).
  3. Review guard (409).

  Unauthorised users get 403 without seeing which content is unreviewed.
- **`POST /admin/scenarios/{id}/versions/{v}/status` → `published`:**
  - Still requires a published KB, with the same 409 message as before.
  - Now also requires that published KB to be clean (`code: "kb_not_clean"`). This only matters for a KB published before the guard existed; none exists in production today (`merchant_onboarding` 1.0.0 has no flags).
- **The guard never edits content.** Clearing `needs_review` and `draft_note` remains a deliberate edit of a draft version by the product team.

### A0-5 — The 60-point cap is always explained
- **New pure function `cap_reason(result, claim_checks, weights)`** in `app/scoring_math.py`. It uses the existing `has_critical_error` and `compute_total`, so it can't disagree with the total, and it makes no model call.
- **When it returns a reason:** only when the cap actually lowered the score, i.e. a trigger exists **and** the uncapped total is above 60. The reason has this shape:
  ```json
  {"limit": 60, "calculated_total": 74,
   "triggers": [{"kind": "critical_error", "type": "...", "quote": "...", "explanation": "..."},
                {"kind": "claim", "verdict": "unapproved|forbidden", "claim_text": "...", "turn_index": 3, "reason": "..."}]}
  ```
- **`GET /sessions/{id}/score`** now includes `cap_reason`: the object above, or `null`. It's computed at read time from the stored breakdown, critical errors and claim checks. The weights are the same ones `finalize()` used: the rubric plus the session's bound scenario-version overrides.
- **`static/app.js` (minimal UI fix, no redesign).** The old line "Есть критичная ошибка — итог ограничен 60 баллами" showed whenever any critical error existed, even when nothing was capped. It's replaced by a note shown only when `cap_reason` is present. The note gives the uncapped total and lists each trigger.

### A1-0 — One approval policy point, no behaviour change
- **New `can_transition(user, version, target) -> TransitionDecision`** in `app/content.py`. It picks the role sets from the version's type (`ScenarioVersion` or `KnowledgeBase`) and applies the existing lifecycle graph and role rules.
- **New `require_transition(...)`** raises the same `HTTPException` (same status codes and messages) as before.
- **The old `check_transition(...)`** (6 parameters, role sets passed by each endpoint) is removed; both endpoints call the policy.
- **Four-eyes rules aren't implemented.** The docstring marks this function as the single place for them once the bank decides B-1/B-2.

### Test-harness fix (outside the three items, flagged)
- **New `pytest.ini`** (`testpaths = tests`, `python_files = test_*.py`).
- **Why:** `pytest tests` also collected `tests/run_gate_test.py` (it matches pytest's default `*_test.py` pattern). That file imports the app before the test modules configure it, so `pytest tests` failed even on the base commit: 18 failed and 20 errors out of the original 43 tests. The README's command (`pytest tests/test_access.py`) was unaffected.
- **Effect:** `pytest`, `pytest tests` and per-file runs now all give the same result. The gate script itself is unchanged and still run manually.

## Files changed

| File | Change |
|---|---|
| `app/content.py` | `TransitionDecision`, `can_transition`, `require_transition`, `kb_review_blockers`, `kb_review_message`; `check_transition` removed |
| `app/routers/admin.py` | Both status endpoints call `require_transition`; KB review guard; clean-KB check on scenario publish; `_review_conflict` helper |
| `app/scoring_math.py` | `cap_reason` added; **no existing line changed** |
| `app/main.py` | `/score` returns `cap_reason` |
| `static/app.js` | `capNote()` replaces the unconditional cap sentence |
| `tests/test_phase1.py` | New, 22 tests |
| `pytest.ini` | New (see above) |
| `PILOT_READINESS_PLAN.md`, `PILOT_READINESS_AUDIT.md` | Phase 1 items marked |

**Not changed:**
- AI prompts (`app/prompts.py`) and providers.
- Rubric, weights and seed data.
- `compute_total`, `finalize`, `has_critical_error`.
- Models and schema, `app/security.py` role sets.
- Deployment config and dependencies.

## Database / schema changes
None. No migration, no `init_db` run needed.

## Tests added (`tests/test_phase1.py`, 22)

| Group | Tests |
|---|---|
| Approval policy (A1-0) | **Exhaustive equivalence:** for both content types, every role (6 + unknown) × current status (4) × target (4 + invalid), 140 cases per type, the new policy returns exactly what a frozen copy of the old `check_transition` returned (allowed, status code, message). No four-eyes rule: an author can still approve their own version when the role allows it. Unknown content type is rejected. |
| KB guard (A0-1) | Blocker detection (unit) · placeholder KB can't be approved (409, 6 items listed, status stays `draft`) · placeholder KB in `approved` can't be published (status stays `approved`) · `draft_note` alone blocks · blocked transition writes no audit row · clean KB goes draft → approved → published, and published stays immutable (409 on edit) · 403/400 still precede 409 · scenario publish still needs a published KB · scenario publish blocked against an unclean published KB (status stays `approved`, not live) · scenario publishes against a clean KB, and a new session binds scenario v1 + KB 1.0.0 |
| Score cap (A0-5) | 100 + critical → 60 · 74 + critical → 60 · 42 + critical → 42 · no trigger → unchanged · `cap_reason` unit cases (critical error, unapproved claim, forbidden claim, approved claim ignored, ≤60 → none) · `cap_reason` present **iff** `finalize()` lowered the total (16 combinations) · API: 100 + critical error → 60 with reason · 74 + **unapproved claim with empty `critical_errors`** (the audit's silent-cap case) → 60 with claim trigger · forbidden claim → 60 · 42 + critical → 42, `cap_reason: null` · approved claim → unchanged · every API case checks version linkage (scenario v1, KB 1.0.0) |

## Test results
```
pytest                                     65 passed   (43 existing + 22 new)
pytest tests                               65 passed
pytest tests/test_phase1.py tests/test_access.py   65 passed (reverse order)
pytest tests/test_access.py                43 passed
pytest tests/test_phase1.py                22 passed
```
Run from a copy of the repo with offline (stub) providers and a temporary SQLite database. The real-model gate test (`tests/run_gate_test.py`) wasn't run: it costs API credit and the scoring prompts and algorithm are unchanged.

**Manual regression on a local server (stub providers):**
- Placeholder `rko` approve → 409 listing 6 items; status stays `draft`.
- `merchant_onboarding` new version 1.1.0 → approved → published; 1.0.0 archived; editing published 1.1.0 → 409.
- Scenario approve → publish works; publishing a scenario whose KB is unpublished → 409 (unchanged message).
- Session binds scenario v1 + KB 1.1.0 → finish → score-run → `/score` returns versions and `cap_reason` (null when uncapped).

## Behaviour before → after

| Situation | Before | After |
|---|---|---|
| Approve or publish a KB with `needs_review` or `draft_note` | Allowed (UI warning only) | 409 `kb_unreviewed` listing the entries; status unchanged |
| Publish a scenario whose product's published KB has unreviewed entries | Allowed | 409 `kb_not_clean` |
| Any other status change (scenario or KB) | Rules in `check_transition` | Identical outcomes via `can_transition` (proven exhaustively) |
| Score capped by an unapproved/forbidden claim with no `critical_errors` entry | 60 shown with no explanation | 60 shown with "Итог ограничен 60 баллами (без ограничения было бы N), потому что: …" |
| Critical error, score already ≤ 60 | Text claimed the score was "ограничен 60" | No cap note (nothing was capped); the critical error is still listed in its own section |
| Total, weights, cap rule | — | Unchanged |

## Known limitations
- **The seed loader bypasses the guard.** `seed/knowledge_base.json` can still insert a KB as `published` via `seed_status`. It's developer-controlled, and the only seeded published KB is clean.
- **The admin UI shows the 409 message as before**, now with the IDs listed. A structured display of `unreviewed` belongs to the Phase 7 editors.
- **`cap_reason` is computed at read time, not stored.** It's deterministic from stored data. If a session's scenario-version weights were edited in place it would differ, but approved and published versions are immutable, so that can't happen to a scored session.
- **Older sessions:** sessions scored before Block 4 weights existed use the rubric defaults, which is what they were scored with.

## Bank-dependent items deliberately not implemented
- **Four-eyes / segregation of duties (B-1):** editor ≠ approver, mandatory second approver, product and compliance dual approval, admin bypass, new statuses. None added; `can_transition` is where they will go.
- **Who approves what (B-2):** role sets unchanged.
- Everything else in category B (providers, hosting, retention, SSO, provisioning, security requirements) and category C (bank product content).

## Deployment
No environment variable, dependency, schema or infrastructure change. Deploying is a normal code deploy, not done (not requested).
