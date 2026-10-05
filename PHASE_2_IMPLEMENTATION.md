# Phase 2 — P0 test coverage: implementation record

**Date:** 2026-10-05 · **Base:** Phase 1b commit `507b698` · **Scope:** tests only
**Application code changed: NO.** (`git diff 507b698 -- app static seed` is empty.)
**Git:** uncommitted, for review. Nothing pushed or merged.

## 1. Initial coverage matrix (before Phase 2, 116 tests)

| # | Requirement | Existing tests | Status before |
|---|---|---|---|
| 1 | Scoring arithmetic | 1b `test_valid_output_scores_exactly_as_before`, dedup/unknown tests | **Partial:** override rules, clamping, zero / all-zero weights, omitted criteria, rounding not pinned down |
| 2 | 60-point cap | P1 `test_cap_never_raises_a_score`, `test_cap_reason_*`, `test_api_*`; 1b cap/duplicate tests | **Full** |
| 3 | Hidden scenario fields | — | **Missing** |
| 4 | Scenario-version binding | P1 `test_scenario_publishes_against_clean_kb_and_binds_versions` (binding at start only) | **Partial** |
| 5 | KB-version binding | — | **Missing** |
| 6 | KB enforcement | P1 publish guards; access `test_draft_scenario_cannot_be_started`, `test_manager_sees_only_published_scenarios` | **Partial:** manager reads of KB routes, archived KB under a live scenario, binding with newer versions present |
| 7 | Session ownership / IDOR | access `test_session_visibility` (2 read routes × 5 roles), `test_only_owner_can_write` (dispute only) | **Partial:** no product role, other-team lead, write routes, audio, unknown IDs |
| 8 | Role × route authorization | P1 policy-function equivalence (280 cases); access user-admin and audit tests | **Partial:** no endpoint-level content matrix |
| 9 | Critical-error persistence | P1 API tests read `critical_errors` back | **Partial:** exact fields, cross-role re-read and audit unchecked |
| 10 | Claim verdict persistence | 1b `test_persisted_claims_are_canonical_and_complete` | **Mostly full:** `matched_entry_id` and cross-role re-read unchecked |
| 11 | Result visibility | access `test_session_visibility` | **Partial** (same gaps as 7) |
| 12 | Content lifecycle invariants | P1 policy equivalence, published-KB immutability, clean lifecycle | **Partial:** "publish archives previous" and "edit of published scenario creates new version" untested |
| — | Auth edge cases (plan §8, P0) | access login/logout/tampered cookie | **Partial:** expired cookie, deactivated user's live cookie untested |

## 2. Tests added (239)

| File | Tests | Covers |
|---|---|---|
| `tests/test_phase2_hidden_fields.py` | 6 | #3. Unique sentinel **values** in all 12 hidden client fields, the `objections` list, a hidden variant field (`urgency`) and coaching material (`good_examples`, `feedback_hints`). None appear in any manager response: catalogue (manager and lead), session creation, text turn, voice turn, transcript, audio, score while active and scoring, history, `/auth/me`, `/products`, `/rubric`. Visible briefing fields and visible variants **are** shown. The AI client prompt contains every hidden client value on every turn (and exactly the drawn variant); the scorer receives the coaching material; the training team can still read what it wrote. |
| `tests/test_phase2_version_binding.py` | 4 | #4, #5, #6, #12. **Scenario:** v1 published → session → v2 published mid-session (v1 archived) → the running session's prompt keeps v1 pain and difficulty, scoring uses v1 goal, hints and **weights** (total 100 vs 0 under v2), result and re-read report v1; a new session gets v2. **KB:** same lifecycle: prompt and claim checker see only v1 facts, objections and forbidden list; result and transcript report 1.0.0; a new session binds 2.0.0. Session binds only the *published* KB when newer approved or draft versions exist. Archiving a KB hides its scenario and blocks new sessions (409) while a running session continues on its snapshot. |
| `tests/test_phase2_session_access.py` | 98 | #7, #11. Every session route × 8 callers (owner, other manager, same-team lead, other-team lead, training, product, compliance, admin). **Reads** (transcript, score, audio): 200 only for owner, same-team lead, admin. **Writes** (text turn, voice turn, finish, score-run, dispute): 403 for all 7 non-owners **and the session state is unchanged** after each refusal. Owner can use every write route. Unknown session ID → 404 `{"detail": "session not found"}` for every route and caller. History lists only own sessions; lead drill-down follows the team. |
| `tests/test_phase2_content_authz.py` | 109 | #8, #12. HTTP-level matrix for all 6 roles: 6 content reads; scenario create, edit (published → new draft v2, v1 untouched), approve, publish, archive, back-to-draft; KB create, edit draft, approve, publish, archive, back-to-draft. Each case starts from freshly created content in the right state, and **refused calls change nothing**. Documents that one admin can still run the whole chain alone (B-1 pending). |
| `tests/test_phase2_scoring.py` | 19 | #1, #9, #10. `effective_weights` (defaults, partial override, negative → 0, None ignored, unknown ignored, rubric not mutated); `compute_total` (normalisation, clamp to max and 0, zero/missing max ignored, zero-weight criterion, all-zero → 0, omitted criterion counts 0, **round-half-to-even** documented, fractional score truncated, order independence, full/empty marks); `finalize` records effective weights. **Persistence:** critical errors (type, quote, explanation), all three claim verdicts with text, turn, `matched_entry_id`, reason, breakdown reasons and quotes, versions, `cap_reason`: identical when re-read by owner, team lead and admin. `session.scored` audit row carries versions, total and error types. History row matches. Re-scoring after a failure doesn't duplicate stored claims. |
| `tests/test_phase2_auth.py` | 3 | Auth (plan §8 P0): a validly signed but expired cookie → 401; a deactivated user's existing cookie stops working on the next request; a role change applies to an existing cookie at once. |
| `tests/support.py` | — | Shared offline setup and helpers for the Phase 2 files (not collected). Every helper creates uniquely named products, scenarios, teams and users. An autouse module fixture archives any scenario that became live during the module, so the shared catalogue is unchanged for other modules. |

## 3. Tests intentionally NOT added (already proven)

- 60-cap cases 100/74/42/no-trigger and `cap_reason` ↔ `finalize` agreement: Phase 1.
- Duplicate/unknown criteria, valid-output equivalence, verdict normalisation and fail-closed: Phase 1b.
- Approval policy over every role × status × target: Phase 1 (280 cases). Phase 2 tests the HTTP wiring once per role and target instead of re-enumerating.
- Unreviewed-KB guard, dirty legacy KB, "scenario needs a published KB": Phase 1.
- Draft-only products in `/products`: Phase 1b.
- Login, logout, tampered cookie, admin lockout protection: original suite.

## 4. Bugs discovered
**None in the application during Phase 2.** (The three found at the start of Phase 2 were fixed in Phase 1b.)

**Test-isolation issue found and fixed in test code only:**
- **Cause:** new modules left published scenarios in the shared test DB. `test_access.py::test_manager_sees_only_published_scenarios`, which asserts the exact catalogue, then failed in some file orders.
- **Fix:** the snapshot-and-archive fixture in `tests/support.py`. Existing tests are unchanged.

**Documented current behaviour worth knowing (not bugs, not changed):**
- **Rounding:** `compute_total` uses Python's round-half-to-even (12.5 → 12, 37.5 → 38). It's only reachable with scenario weight overrides; default weights give whole points.
- **Omitted criteria:** a criterion missing from the breakdown counts as 0 (since Phase 1b the provider also rejects such output).
- **Audio replay:** same-team leads and admins can replay a session's client audio, which re-synthesises it (TTS cost).
- **No four-eyes check:** one admin can create, approve and publish content alone (bank decision B-1).

## 5. Remaining P0 test gaps
These depend on Phase 3 behaviour changes. They're untestable as "correct" today because the current behaviour is the problem:

| Gap | Why it waits | Phase |
|---|---|---|
| Login throttling, failed-login audit | Not implemented (A0-6) | 3 |
| AI provider failures: dialog/STT/TTS errors return a friendly code, transcript equals screen, no raw provider text | Current behaviour is unhandled 500 / raw text (A0-3, A0-4) | 3 |

Also not run: the real-model gate test (`tests/run_gate_test.py`). It costs money, and Phase 2 changed no scoring code.

## 6. Files changed
New: `tests/support.py`, `tests/test_phase2_hidden_fields.py`, `tests/test_phase2_version_binding.py`, `tests/test_phase2_session_access.py`, `tests/test_phase2_content_authz.py`, `tests/test_phase2_scoring.py`, `tests/test_phase2_auth.py`, `PHASE_2_IMPLEMENTATION.md`. Updated: `PILOT_READINESS_PLAN.md` (Phase 2 coverage marked).
Unchanged: every application, static, seed and config file; all existing tests.

## 7. Full test results (offline, stub providers, temporary SQLite, no credentials)
```
pytest                                         355 passed
pytest tests                                   355 passed
test_access.py                                  43 passed
test_phase1.py                                  22 passed
test_phase1b.py                                 51 passed
test_phase2_auth.py                              3 passed
test_phase2_content_authz.py                   109 passed
test_phase2_hidden_fields.py                     6 passed
test_phase2_scoring.py                          19 passed
test_phase2_session_access.py                   98 passed
test_phase2_version_binding.py                   4 passed
reverse order (phase2 → 1b → 1 → original)     355 passed
shuffled order                                 352 passed (before auth file was added)
phase 2 first, then original, 1, 1b            352 passed (before auth file was added)
auth first + reverse order                     355 passed
```
Test count: **116 → 355** (+239).
