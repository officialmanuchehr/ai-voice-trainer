# Phase 1b — Scoring and content safety gaps: implementation record

**Date:** 2026-10-05 · **Base:** Phase 1 commit `ed9a93a` (not amended) · **Scope:** the three bugs found at the start of Phase 2, fixes approved as specified.

---

## Bug 1 — Duplicate or invalid scoring criteria could inflate the score

**Root cause:**
- The scoring output schema (`_build_score_schema`) lets `criterion_id` be any string and doesn't require uniqueness.
- `compute_total` added up every breakdown entry, so a repeated criterion counted twice. Reproduced: full marks plus a duplicate gave **115/100**; half marks plus 3 duplicates went from **49 to 94**.

**Fix (both layers):**
1. **Provider validation.** `ClaudeScoringProvider.score` checks the breakdown with the new `scoring_math.breakdown_problems(breakdown, rubric)`: every rubric criterion exactly once, no duplicates, no unknown IDs, none missing. If any problem is found, it raises `ValueError` inside the **existing** retry loop (`MAX_ATTEMPTS = 3`). After 3 bad answers it raises `RuntimeError`, so the session ends in `finish_error` (retryable). Malformed output is never accepted.
2. **Scoring safety net.** `compute_total` counts each criterion **once**: the first usable entry (known criterion, weight > 0, max > 0) wins, and later duplicates are ignored. Unknown criteria still contribute nothing (unchanged).

**Not changed:**
- Rubric weights or their meaning, scenario overrides.
- The model-returned `max` (deliberately **not** forced to the rubric weight).
- Score clamping, rounding, normalisation, the 60 cap.

For valid output, where each criterion appears once, `compute_total` returns exactly what it did before. This is proven against a frozen copy of the old function over 4 weight configurations × 6 score levels × capped/uncapped.

## Bug 2 — An unrecognised claim verdict bypassed the anti-mis-selling cap

**Root cause:**
- The claim-verification pass has no output schema; its JSON was only checked to be a list.
- Verdicts were saved as returned.
- `has_critical_error` matches only the exact strings `unapproved` and `forbidden`. So `"unsupported"`, `"Unapproved"`, `""` and similar counted as safe: fail-open.

**Fix (both layers):**
1. **Provider validation.** `ClaudeScoringProvider.verify_claims` normalises each verdict with `scoring_math.canonical_verdict`: trim, lower-case, must be `approved`, `unapproved` or `forbidden`. It also requires each claim to be an object. Anything else raises `ValueError` in the existing retry loop; after 3 bad answers, `RuntimeError` → `finish_error`. Valid verdicts are returned in canonical form.
2. **Backend safety boundary,** independent of any provider. In `_run_scoring` (`app/main.py`), right after `verify_claims` and **before** claims are saved or passed to scoring and `finalize`, every verdict goes through `scoring_math.fail_closed_verdict`:

   | Input | Result |
   |---|---|
   | `approved` / `unapproved` / `forbidden` (any case, surrounding whitespace) | that verdict |
   | anything else (`unsupported`, random text, `""`, missing) | `unapproved` |

   No fourth verdict exists, nothing unknown becomes `approved`, and `forbidden` is unchanged.

`has_critical_error`, `CRITICAL_VERDICTS` and the cap rule are untouched. The bypass is closed because only canonical verdicts reach them.

## Bug 3 — `/products` exposed draft-only product metadata

**Root cause:**
- Creating a first KB version for a new product also creates the `Product` row from that draft's `name` and `segment`.
- `GET /products` returned every product to every logged-in user.

**Fix:**
- `list_products` (`app/main.py`): roles outside `CONTENT_VIEW_ROLES` (manager, sales lead) see only products that have a **published** KB. Draft-only products, including their name, segment and existence, aren't listed.
- Training, product, compliance and admin see all products, as before.
- Published products are unchanged. KB permissions are untouched.

**Visible side effect:** managers and leads no longer see the seeded draft-only products (РКО, Зарплатный проект, Кредит) in `/products`, which the dashboard's product filter uses. They reappear automatically once their KBs are published.

---

## Files changed

| File | Change |
|---|---|
| `app/scoring_math.py` | `VERDICTS`, `canonical_verdict`, `fail_closed_verdict`, `breakdown_problems` added; `compute_total` counts each criterion once (2 lines replaced, 4 added) |
| `app/providers/claude_scoring.py` | `verify_claims` normalises and validates verdicts; `score` validates the breakdown. Both use the existing retry loop. **No prompt, model, schema or call change.** |
| `app/main.py` | Fail-closed verdicts in `_run_scoring` before persisting and scoring; `/products` filtered for non-content roles |
| `tests/test_phase1b.py` | New, 51 tests |
| `PILOT_READINESS_PLAN.md` | Phase 1b noted |

Untouched (zero diff): `app/prompts.py`, the dialog, STT and TTS providers, `app/models.py`, `app/security.py`, `seed/`, rubric, config, `vercel.json`, `requirements.txt`.

## Tests added (`tests/test_phase1b.py`, 51)

| Area | Tests |
|---|---|
| Bug 1 — safety net | Duplicate can't exceed full marks (100, not 115) · duplicate can't inflate a partial score (49, not 94) · first occurrence wins · first *usable* occurrence wins over an unusable one · unknown criterion contributes nothing · **valid output identical to the old function** (48 combinations) · cap unchanged with duplicates (60 / 42) · `finalize` not inflated · `breakdown_problems` cases · API: duplicates reaching `finalize` don't inflate the stored total |
| Bug 1 — provider | Duplicate / unknown / missing criterion each trigger a retry and the valid second answer is used · persistent malformed output → `RuntimeError` after `MAX_ATTEMPTS` · valid output accepted first time, unchanged |
| Bug 2 — provider | `" Approved "`, `"Unapproved"`, `"FORBIDDEN"` normalised · `unsupported`, random, `""`, `None`, non-string → retry · non-object claim → retry · persistent unknown → `RuntimeError` · empty claim list accepted |
| Bug 2 — backend boundary (provider bypassed) | `fail_closed_verdict` table (10 cases) · `canonical_verdict` is strict · API: `unsupported`, random, `""` and Cyrillic text each stored as `unapproved` and cap the score at 60 with an explained reason · `FORBIDDEN` still caps and is stored as `forbidden` · `" Approved "` stored as `approved` and doesn't cap (90 stays 90) · persisted claims are canonical, with text, turn and reason intact |
| Bug 3 | Sentinels `SECRET_DRAFT_PRODUCT_NAME_123`, `SECRET_DRAFT_SEGMENT_456` and the product ID are absent from `/products` for manager and lead · training, product, compliance and admin still see the product with its name and segment · after the KB is approved and published the product appears for manager and lead · merchant product still visible, seeded drafts hidden · lead dashboard still loads |

**Tests catch the bugs:** the same file run against the Phase 1 code (with the new helpers present but not wired in) gives **28 failed, 23 passed**. Every bug-specific test fails, and only the "behaviour unchanged" tests pass.

## Test results
```
pytest                                                       116 passed
pytest tests                                                 116 passed
pytest tests/test_phase1b.py                                  51 passed
pytest tests/test_phase1.py                                   22 passed
pytest tests/test_access.py                                   43 passed
pytest tests/test_phase1b.py tests/test_phase1.py tests/test_access.py   116 passed
pytest tests/test_phase1.py tests/test_phase1b.py tests/test_access.py   116 passed
```
All offline (stub providers, temporary SQLite). No paid gate test, no production credentials.

**Real-model compatibility check:** the recorded real-Claude results in `tests/fixtures/` (honest and mis-selling dialogues) pass the new breakdown validation and contain only canonical verdicts. The stricter validation therefore isn't expected to increase `finish_error` rates.

## Behaviour before → after

| Situation | Before | After |
|---|---|---|
| Evaluator repeats a criterion | Summed; total could exceed 100 | Provider retries; if it still reaches scoring, only the first entry counts |
| Evaluator returns an unknown or missing criterion | Unknown ignored; missing scored 0, accepted | Provider retries; after 3 failures `finish_error` (retryable) |
| Claim verdict `"Unapproved"`, `" FORBIDDEN "` | Treated as safe, no cap | Normalised; caps as intended |
| Claim verdict `"unsupported"`, `""`, random | Treated as safe, no cap | Provider retries; if it still reaches the backend, stored and scored as `unapproved` (caps) |
| Valid evaluator output | — | Identical totals, cap, `cap_reason` |
| Manager or lead calls `/products` | All products incl. draft-only | Only products with a published KB |
| Content roles call `/products` | All products | All products (unchanged) |

## Invariants verified
1. **KB is the source of truth:** prompts, facts and KB binding untouched (full suite green).
2. **No unreviewed KB can be approved or published:** Phase 1 tests green.
3. **Unknown claim verdicts fail closed:** provider and backend tests.
4. **Malformed criteria can't inflate a score:** safety-net and provider tests.
5. **The 60-point cap is unchanged:** cap tests from Phase 1 and Phase 1b.
6. **Scenario and KB version binding unchanged:** Phase 1 linkage assertions green.
7. **Draft KB facts stay inaccessible to managers and leads:** `/kb/*` and `/admin/*` still 403 (Phase 2 probe, unchanged code).
8. **Draft-only product metadata is hidden from managers and leads:** Bug 3 tests.
9. **RBAC outside these fixes is unchanged:** 43 access tests and the 280-case policy equivalence.
10. **No AI prompt or product fact changed:** zero diff on `app/prompts.py` and `seed/`.

## Regressions found
None.

## Database / schema impact
None. No migration.
- **Existing claim rows** keep their stored verdicts. Rows written by the real Claude scorer so far are expected to be canonical, which the recorded fixtures confirm.
- **New rows are always canonical.**

## Deployment / environment impact
None: no env var, dependency or infrastructure change. A normal code deploy, not performed.
