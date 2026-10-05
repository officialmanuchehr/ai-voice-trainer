"""Deterministic total computation, applied after every scoring run.

The scorer always grades each criterion on the rubric's own scale (its anchors
are written for the default weights). A scenario may re-weight criteria (PRD
§12 «задавать веса критериев») — that is applied here, in Python, by scaling
each criterion's share and normalising to 100, so the model never has to
re-interpret anchors or do arithmetic.
"""

CRITICAL_VERDICTS = {"unapproved", "forbidden"}
CRITICAL_CAP = 60


def effective_weights(rubric: dict, overrides: dict | None) -> dict[str, int]:
    weights = {c["id"]: int(c["weight"]) for c in rubric.get("criteria", [])}
    for criterion_id, weight in (overrides or {}).items():
        if criterion_id in weights and weight is not None:
            weights[criterion_id] = max(0, int(weight))
    return weights


def has_critical_error(result: dict, claim_checks: list[dict]) -> bool:
    return bool(result.get("critical_errors")) or any(c.get("verdict") in CRITICAL_VERDICTS for c in claim_checks)


def compute_total(breakdown: list[dict], weights: dict[str, int], critical: bool) -> int:
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0
    points = 0.0
    for item in breakdown:
        weight = weights.get(item.get("criterion_id"), 0)
        maximum = int(item.get("max") or 0)
        if weight <= 0 or maximum <= 0:
            continue
        score = min(max(int(item.get("score", 0)), 0), maximum)
        points += score / maximum * weight
    total = round(points * 100 / total_weight)
    return min(total, CRITICAL_CAP) if critical else total


def finalize(result: dict, rubric: dict, claim_checks: list[dict], weight_overrides: dict | None) -> dict:
    weights = effective_weights(rubric, weight_overrides)
    for item in result.get("breakdown", []):
        item["weight"] = weights.get(item.get("criterion_id"), 0)
    result["total"] = compute_total(result.get("breakdown", []), weights, has_critical_error(result, claim_checks))
    return result


def cap_reason(result: dict, claim_checks: list[dict], weights: dict[str, int]) -> dict | None:
    """Why the total was capped, or None when the cap did not change it.

    Built only from what scoring already produced — the stored breakdown,
    critical_errors and claim verdicts — using the same rule as compute_total,
    so it can never disagree with the total and needs no model call. A
    critical error on a result already at or below the cap is not a cap
    (the cap never raises a score), so it yields None."""
    if not has_critical_error(result, claim_checks):
        return None
    calculated = compute_total(result.get("breakdown", []), weights, critical=False)
    if calculated <= CRITICAL_CAP:
        return None
    triggers = [
        {"kind": "critical_error", "type": e.get("type"), "quote": e.get("quote"), "explanation": e.get("explanation")}
        for e in result.get("critical_errors") or []
    ]
    triggers += [
        {
            "kind": "claim",
            "verdict": c.get("verdict"),
            "claim_text": c.get("claim_text"),
            "turn_index": c.get("turn_index"),
            "reason": c.get("reason"),
        }
        for c in claim_checks
        if c.get("verdict") in CRITICAL_VERDICTS
    ]
    return {"limit": CRITICAL_CAP, "calculated_total": calculated, "triggers": triggers}
