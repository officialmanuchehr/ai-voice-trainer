"""Phase 2 — scoring arithmetic (current behaviour, documented) and
persistence of everything scoring produces.

Not repeated here (already proven): the 60 cap 100/74/42 cases and
cap_reason (test_phase1.py); duplicate/unknown criteria, valid-output
equivalence and verdict normalisation (test_phase1b.py).
"""

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    archive_published_scenarios,
    CRITERIA,
    Capture,
    finish_and_score,
    login,
    new_team_with_users,
    ok,
    say,
    server,
    start_session,
)

from app.scoring_math import compute_total, effective_weights, finalize
from app.seed_loader import load_rubric

RUBRIC = load_rubric("rubric_sales_100")
DEFAULT = {c["id"]: c["weight"] for c in RUBRIC["criteria"]}
SEED_SCENARIO = "scn_merchant_onboarding_medium_01"


# ------------------------------------------------------- effective weights


def test_default_weights_are_the_rubric_weights():
    assert effective_weights(RUBRIC, None) == DEFAULT
    assert effective_weights(RUBRIC, {}) == DEFAULT
    assert sum(DEFAULT.values()) == 100


def test_scenario_override_replaces_only_listed_criteria():
    weights = effective_weights(RUBRIC, {"needs": 40, "next_step": 0})
    assert weights == {**DEFAULT, "needs": 40, "next_step": 0}


def test_override_edge_values():
    weights = effective_weights(RUBRIC, {"contact": -5, "needs": None, "not_a_criterion": 50})
    assert weights["contact"] == 0  # negative clamped to 0
    assert weights["needs"] == DEFAULT["needs"]  # None ignored
    assert "not_a_criterion" not in weights  # unknown ignored


def test_overrides_do_not_mutate_the_rubric():
    effective_weights(RUBRIC, {"contact": 99})
    assert load_rubric("rubric_sales_100")["criteria"][0]["weight"] == 10


# ------------------------------------------------------------ compute_total


def total(breakdown, weights, critical=False):
    return compute_total(breakdown, weights, critical)


def test_normalised_to_100_whatever_the_weight_sum():
    breakdown = [{"criterion_id": "a", "score": 1, "max": 2}, {"criterion_id": "b", "score": 2, "max": 2}]
    assert total(breakdown, {"a": 1, "b": 1}) == 75
    assert total(breakdown, {"a": 30, "b": 30}) == 75  # same shares, different scale


def test_score_is_clamped_to_its_max_and_to_zero():
    assert total([{"criterion_id": "a", "score": 15, "max": 10}], {"a": 100}) == 100
    assert total([{"criterion_id": "a", "score": -4, "max": 10}], {"a": 100}) == 0


def test_criterion_with_no_or_zero_max_is_ignored():
    assert total([{"criterion_id": "a", "score": 5, "max": 0}, {"criterion_id": "b", "score": 5, "max": 5}], {"a": 50, "b": 50}) == 50
    assert total([{"criterion_id": "a", "score": 5}], {"a": 100}) == 0


def test_zero_weight_criterion_does_not_count():
    breakdown = [{"criterion_id": "a", "score": 0, "max": 10}, {"criterion_id": "b", "score": 10, "max": 10}]
    assert total(breakdown, {"a": 0, "b": 50}) == 100


def test_all_zero_weights_give_zero():
    assert total([{"criterion_id": "a", "score": 10, "max": 10}], {"a": 0}) == 0
    assert total([{"criterion_id": "a", "score": 10, "max": 10}], {}) == 0


def test_omitted_criterion_counts_as_zero():
    """A criterion missing from the breakdown still weighs in the denominator."""
    assert total([{"criterion_id": "a", "score": 10, "max": 10}], {"a": 50, "b": 50}) == 50


def test_rounding_is_pythons_round_half_to_even():
    """Documents current behaviour: 12.5 -> 12, 37.5 -> 38 (only reachable with
    weight overrides; default weights always give whole points)."""
    assert total([{"criterion_id": "a", "score": 1, "max": 1}], {"a": 1, "b": 7}) == 12
    assert total([{"criterion_id": "a", "score": 1, "max": 1}], {"a": 3, "b": 5}) == 38


def test_fractional_score_is_truncated():
    assert total([{"criterion_id": "a", "score": 7.9, "max": 10}], {"a": 100}) == 70


def test_order_of_criteria_does_not_matter_and_result_is_deterministic():
    breakdown = [{"criterion_id": c["id"], "score": c["weight"] // 3, "max": c["weight"]} for c in RUBRIC["criteria"]]
    first = total(breakdown, DEFAULT)
    assert all(total(list(reversed(breakdown)), DEFAULT) == first for _ in range(5))


def test_default_rubric_full_and_empty_marks():
    full = [{"criterion_id": c, "score": DEFAULT[c], "max": DEFAULT[c]} for c in CRITERIA]
    assert total(full, DEFAULT) == 100
    assert total([{**b, "score": 0} for b in full], DEFAULT) == 0


def test_finalize_records_effective_weight_on_each_criterion():
    result = finalize({"breakdown": [{"criterion_id": "needs", "score": 15, "max": 15}], "critical_errors": []}, RUBRIC, [], {"needs": 40})
    assert result["breakdown"][0]["weight"] == 40
    assert result["total"] == round(40 * 100 / (100 - 15 + 40))


# --------------------------------------------------------------- persistence

CRITICAL = {"type": "Гарантия, которой нет в утверждённых материалах.", "quote": "Гарантирую одобрение", "explanation": "Такой гарантии нет в БЗ."}
CLAIMS = [
    {"claim_text": "Подключение бесплатное", "turn_index": 1, "verdict": "approved", "matched_entry_id": "fact_free_connection", "reason": "есть в БЗ"},
    {"claim_text": "Лимит 500 000 без комиссии", "turn_index": 3, "verdict": "unapproved", "matched_entry_id": None, "reason": "нет в БЗ"},
    {"claim_text": "Гарантирую одобрение", "turn_index": 5, "verdict": "forbidden", "matched_entry_id": None, "reason": "запрещено"},
]


@pytest.fixture(scope="module")
def team(server):
    return new_team_with_users({"manager": "manager", "lead": "sales_lead"})


def test_scoring_output_survives_reload_for_every_reader(team, monkeypatch):
    breakdown = [{"criterion_id": c, "score": 80, "max": 100, "reason": f"причина {c}", "quote": f"цитата {c}"} for c in CRITERIA]
    Capture(monkeypatch, breakdown=breakdown, claims=CLAIMS, critical_errors=[CRITICAL])
    manager = login(team["manager"])
    session_id = start_session(manager, SEED_SCENARIO)["id"]
    for text in ("Подключение бесплатное", "Лимит 500 000 без комиссии", "Гарантирую одобрение"):
        say(manager, session_id, text)
    first = finish_and_score(manager, session_id)

    # Re-read by the owner, the team lead and an admin: identical stored result.
    views = [ok(login(user).get(f"/sessions/{session_id}/score")) for user in (team["manager"], team["lead"], "admin")]
    for view in views:
        for key in ("total", "breakdown", "critical_errors", "claim_checks", "scenario_version", "kb_version", "rubric_id", "cap_reason"):
            assert view[key] == first[key], key
    assert [v["own"] for v in views] == [True, False, False]

    assert first["total"] == 60 and first["cap_reason"]["calculated_total"] == 80
    assert first["critical_errors"] == [CRITICAL]
    assert sorted(first["claim_checks"], key=lambda c: c["turn_index"]) == [
        {k: c[k] for k in ("turn_index", "claim_text", "verdict", "matched_entry_id", "reason")} for c in CLAIMS
    ]
    by_id = {b["criterion_id"]: b for b in first["breakdown"]}
    assert by_id["needs"]["reason"] == "причина needs" and by_id["needs"]["quote"] == "цитата needs"
    assert (first["scenario_version"], first["kb_version"]) == (1, "1.0.0")


def test_scoring_is_audited_with_versions_and_errors(team, monkeypatch):
    Capture(monkeypatch, claims=CLAIMS[1:2], critical_errors=[CRITICAL])
    manager = login(team["manager"])
    session_id = start_session(manager, SEED_SCENARIO)["id"]
    say(manager, session_id)
    result = finish_and_score(manager, session_id)
    entry = next(r for r in ok(login("admin").get("/admin/audit?entity_type=session")) if r["entity_id"] == session_id and r["action"] == "session.scored")
    assert entry["details"] == {
        "scenario_id": SEED_SCENARIO,
        "scenario_version": 1,
        "kb_version": result["kb_version"],
        "total": result["total"],
        "critical_errors": [CRITICAL["type"]],
    }


def test_history_reflects_stored_result(team, monkeypatch):
    Capture(monkeypatch, claims=CLAIMS, critical_errors=[CRITICAL, CRITICAL])
    manager = login(team["manager"])
    session_id = start_session(manager, SEED_SCENARIO)["id"]
    say(manager, session_id)
    result = finish_and_score(manager, session_id)
    row = next(r for r in ok(manager.get("/me/sessions")) if r["id"] == session_id)
    assert (row["status"], row["total"], row["critical_errors"]) == ("finished", result["total"], 2)


def test_rescoring_after_error_does_not_duplicate_stored_rows(team, monkeypatch):
    """finish_error -> retry: the stored claims are the retry's, not doubled."""
    import app.main as main

    manager = login(team["manager"])
    session_id = start_session(manager, SEED_SCENARIO)["id"]
    say(manager, session_id)

    async def failing_score(transcript, rubric, claim_checks):
        raise RuntimeError("provider down")

    Capture(monkeypatch, claims=CLAIMS)
    monkeypatch.setattr(main.scoring_provider, "score", failing_score)
    ok(manager.post(f"/sessions/{session_id}/finish"))
    assert ok(manager.post(f"/sessions/{session_id}/score-run"))["status"] == "finish_error"

    Capture(monkeypatch, claims=CLAIMS)
    result = finish_and_score(manager, session_id)
    assert len(result["claim_checks"]) == len(CLAIMS)
