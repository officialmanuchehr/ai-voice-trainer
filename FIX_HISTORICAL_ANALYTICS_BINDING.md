# Fix — historical analytics bound to the session's scenario version

**Date:** 2026-10-05 · **Base:** Phase 5A `ce7d0f8` · **Scope:** `app/analytics.py` only, plus one regression test file. Found during the Phase 5B data inventory.

## Bug
- **Symptom:** after a new version of a scenario was published, sessions bound to an older version were reported with the **new** version's product and difficulty, in manager history, the lead's manager drill-down, and the dashboard's product filter and product table.
- **Correct before and after:** title and version (title already came from the bound version).
- **Never affected:** stored scores, transcripts, critical errors, claim checks and KB version.
- **Reproduction:** v1 (product A, easy) → scored session → v2 (product B, hard) published → the old session's row showed product B and "hard".

## Root cause
- **`session_rows()`:** took `product_id`, `product_name` and `difficulty` from the `Scenario` row, which is the denormalised copy of the **currently published** version.
- **`build_dashboard()`:** used the same row to filter and group sessions by product.

## Fix
- **New helper:** `bound_scenario(session, versions, scenarios)` in `app/analytics.py` returns title, product and difficulty from `ScenarioVersion.data` for `(session.scenario_id, session.scenario_version or 1)`, the version the session was bound to at start.
- **Fallback:** only if that version record doesn't exist, it falls back to the scenario row. Seeding backfills a v1 record for pre-versioning scenarios, so this is defensive.
- **Callers:** `session_rows()` (history and lead drill-down) and `build_dashboard()` (product filter and product breakdown) now use it.
- **Product name:** looked up from the product referenced by the bound version.
- **`scenario_available`:** deliberately still uses the current scenario. It answers "can this be trained now?", not a historical fact.
- **Data:** no historical records are modified or copied; the bound version is read on every request. No schema change.
- **Sufficiency check:** every `ScenarioVersion.data` contains `product_id` and `difficulty` (written by the scenario validator and the seed loader).

## Access and privacy
- **Unchanged:** RBAC, the queries' user and team scoping, and response fields.
- **What's read:** only the version each session is bound to (title, product, difficulty, fields already shown before); no hidden scenario field is read into any response.

## Tests (`tests/test_fix_historical_binding.py`, 4)
- **Fixture:** v1 (product A, easy) → scored session → v2 (product B, hard) published → a new scored session.
- **Session start:** the old session is bound to v1 / A / easy, the new one to v2 / B / hard.
- **`/me/sessions`:** the old row reports v1, "История v1", product A, A's name, "easy"; the new row v2 / B / "hard"; the stored score is unchanged.
- **Lead drill-down:** same binding.
- **Dashboard:** the product table counts one session under A and one under B; the product filter for A and for B each returns exactly its session.

**Against the old code:** 3 failed, 1 passed (session start was always bound).

## Results
- **Full suite:** 479 passed (475 + 4).
- **Version-binding, access and IDOR subsets:** 149 passed.
