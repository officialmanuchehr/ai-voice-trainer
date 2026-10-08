"""Phase 1b: malformed evaluator criteria (bug 1), fail-closed claim verdicts
(bug 2), draft-only products hidden from /products (bug 3).

Offline: stub providers, throwaway SQLite, demo users. The Claude provider is
exercised with canned model responses — no network, no API key.

    pytest tests/test_phase1b.py
"""

import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_DB_FILE = Path(tempfile.mkdtemp()) / "test.db"
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{_DB_FILE}",
        "STT_PROVIDER": "stub",
        "DIALOG_PROVIDER": "stub",
        "SCORING_PROVIDER": "stub",
        "TTS_PROVIDER": "stub",
        "AUTO_INIT_DB": "true",
        "SEED_DEMO_USERS": "true",
        "DEMO_USERS_PASSWORD": "demo12345",
        "SECRET_KEY": "test-secret",
        "INITIAL_ADMIN_USERNAME": "",
        "INITIAL_ADMIN_PASSWORD": "",
        "BASIC_AUTH_USERNAME": "",
        "BASIC_AUTH_PASSWORD": "",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.providers.claude_scoring import MAX_ATTEMPTS, ClaudeScoringProvider  # noqa: E402
from app.scoring_math import (  # noqa: E402
    breakdown_problems,
    canonical_verdict,
    compute_total,
    effective_weights,
    fail_closed_verdict,
    finalize,
)
from app.seed_loader import load_rubric  # noqa: E402

PASSWORD = "demo12345"
SCENARIO = "scn_merchant_onboarding_medium_01"
RUBRIC = load_rubric("rubric_sales_100")
CRITERIA = [c["id"] for c in RUBRIC["criteria"]]
WEIGHTS = effective_weights(RUBRIC, None)


@pytest.fixture(scope="module")
def server():
    with TestClient(app) as client:
        yield client


def login(username: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


def full_marks():
    return [{"criterion_id": c["id"], "score": c["weight"], "max": c["weight"]} for c in RUBRIC["criteria"]]


def half_marks():
    return [{"criterion_id": c["id"], "score": c["weight"] // 2, "max": c["weight"]} for c in RUBRIC["criteria"]]


def _legacy_compute_total(breakdown, weights, critical):
    """Frozen copy of compute_total before Phase 1b — the oracle for valid output."""
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
    return min(total, 60) if critical else total


# ============================================ Bug 1 — scoring safety net


def test_duplicate_criterion_cannot_push_score_above_full_marks():
    assert compute_total(full_marks() + [{"criterion_id": "needs", "score": 15, "max": 15}], WEIGHTS, False) == 100


def test_duplicate_criterion_cannot_inflate_a_partial_score():
    expected = compute_total(half_marks(), WEIGHTS, False)
    duplicates = [{"criterion_id": "needs", "score": 15, "max": 15}] * 3
    assert compute_total(half_marks() + duplicates, WEIGHTS, False) == expected == 49


def test_first_occurrence_of_a_criterion_wins():
    breakdown = [{"criterion_id": "a", "score": 2, "max": 10}, {"criterion_id": "a", "score": 10, "max": 10}]
    assert compute_total(breakdown, {"a": 100}, False) == 20


def test_first_usable_occurrence_wins_over_an_unusable_one():
    breakdown = [{"criterion_id": "a", "score": 9, "max": 0}, {"criterion_id": "a", "score": 7, "max": 10}]
    assert compute_total(breakdown, {"a": 100}, False) == 70


def test_unknown_criterion_cannot_contribute():
    without = half_marks()
    with_unknown = half_marks() + [{"criterion_id": "bonus", "score": 1000, "max": 1}]
    assert compute_total(with_unknown, WEIGHTS, False) == compute_total(without, WEIGHTS, False)


def test_valid_output_scores_exactly_as_before():
    overrides = [None, {"contact": 0}, {"needs": 40, "next_step": 0}, {c: 1 for c in CRITERIA}]
    for override in overrides:
        weights = effective_weights(RUBRIC, override)
        for share in (0, 0.13, 0.5, 0.74, 0.99, 1):
            breakdown = [
                {"criterion_id": c["id"], "score": round(c["weight"] * share), "max": c["weight"]} for c in RUBRIC["criteria"]
            ]
            for critical in (False, True):
                assert compute_total(breakdown, weights, critical) == _legacy_compute_total(breakdown, weights, critical)


def test_cap_unchanged_with_duplicates():
    duplicated = full_marks() + full_marks()
    assert compute_total(duplicated, WEIGHTS, True) == 60
    low = [{"criterion_id": "a", "score": 42, "max": 100}, {"criterion_id": "a", "score": 100, "max": 100}]
    assert compute_total(low, {"a": 100}, True) == 42


def test_finalize_total_not_inflated_by_duplicates():
    result = finalize({"breakdown": half_marks() + full_marks(), "critical_errors": []}, RUBRIC, [], None)
    assert result["total"] == 49


def test_breakdown_problems():
    assert breakdown_problems(full_marks(), RUBRIC) == []
    assert breakdown_problems(full_marks() + [{"criterion_id": "needs"}], RUBRIC) == ["duplicate criteria: ['needs']"]
    assert breakdown_problems(full_marks() + [{"criterion_id": "bonus"}], RUBRIC) == ["unknown criteria: ['bonus']"]
    assert breakdown_problems(full_marks()[1:], RUBRIC) == ["missing criteria: ['contact']"]


def test_api_duplicates_reaching_finalize_cannot_inflate(server, monkeypatch):
    """Even if malformed output got past the provider, the stored total isn't inflated."""
    result = _score_session(monkeypatch, breakdown=half_marks() + full_marks())
    assert result["total"] == 49


# ============================================ Bug 1 / Bug 2 — provider validation


def _provider_with(responses):
    """A ClaudeScoringProvider whose model call returns `responses` in turn
    (no API client is created)."""
    provider = ClaudeScoringProvider.__new__(ClaudeScoringProvider)
    calls = []

    async def fake_call(prompt, output_schema=None):
        calls.append(prompt)
        return responses[min(len(calls), len(responses)) - 1]

    provider._call = fake_call
    return provider, calls


def _score_json(breakdown):
    return json.dumps(
        {
            "breakdown": [{**b, "reason": "r", "quote": "q"} for b in breakdown],
            "critical_errors": [],
            "feedback": {"summary": "s", "strengths": [], "growth_areas": [], "better_examples": [], "next_skill": "n"},
        }
    )


TRANSCRIPT = [{"turn_index": 1, "role": "manager", "text": "Добрый день"}]


@pytest.mark.parametrize(
    "bad",
    [
        full_marks() + [{"criterion_id": "needs", "score": 15, "max": 15}],
        full_marks() + [{"criterion_id": "bonus", "score": 5, "max": 5}],
        full_marks()[:-1],
    ],
    ids=["duplicate", "unknown", "missing"],
)
def test_provider_retries_malformed_breakdown(bad):
    provider, calls = _provider_with([_score_json(bad), _score_json(full_marks())])
    result = asyncio.run(provider.score(TRANSCRIPT, RUBRIC, []))
    assert len(calls) == 2
    assert [b["criterion_id"] for b in result["breakdown"]] == CRITERIA


def test_provider_gives_up_on_persistently_malformed_breakdown():
    provider, calls = _provider_with([_score_json(full_marks()[:-1])])
    with pytest.raises(RuntimeError, match="missing criteria"):
        asyncio.run(provider.score(TRANSCRIPT, RUBRIC, []))
    assert len(calls) == MAX_ATTEMPTS


def test_provider_accepts_valid_breakdown_first_time():
    provider, calls = _provider_with([_score_json(full_marks())])
    result = asyncio.run(provider.score(TRANSCRIPT, RUBRIC, []))
    assert len(calls) == 1
    assert [(b["criterion_id"], b["score"], b["max"]) for b in result["breakdown"]] == [
        (c["id"], c["weight"], c["weight"]) for c in RUBRIC["criteria"]
    ]


def _claims_json(*verdicts):
    return json.dumps([{"claim_text": f"c{i}", "turn_index": 1, "verdict": v, "reason": "r"} for i, v in enumerate(verdicts)])


def test_provider_normalises_verdicts():
    provider, calls = _provider_with([_claims_json(" Approved ", "Unapproved", "FORBIDDEN", "approved")])
    claims = asyncio.run(provider.verify_claims(TRANSCRIPT, {}))
    assert [c["verdict"] for c in claims] == ["approved", "unapproved", "forbidden", "approved"]
    assert len(calls) == 1


@pytest.mark.parametrize("bad_verdict", ["unsupported", "maybe", "", None, 3])
def test_provider_retries_unknown_verdict(bad_verdict):
    provider, calls = _provider_with([_claims_json("approved", bad_verdict), _claims_json("approved", "forbidden")])
    claims = asyncio.run(provider.verify_claims(TRANSCRIPT, {}))
    assert len(calls) == 2
    assert [c["verdict"] for c in claims] == ["approved", "forbidden"]


def test_provider_retries_non_object_claim():
    provider, calls = _provider_with(['["just a string"]', _claims_json("approved")])
    assert asyncio.run(provider.verify_claims(TRANSCRIPT, {}))[0]["verdict"] == "approved"
    assert len(calls) == 2


def test_provider_gives_up_on_persistently_unknown_verdict():
    provider, calls = _provider_with([_claims_json("unsupported")])
    with pytest.raises(RuntimeError, match="invalid claim or verdict"):
        asyncio.run(provider.verify_claims(TRANSCRIPT, {}))
    assert len(calls) == MAX_ATTEMPTS


def test_provider_accepts_empty_claim_list():
    provider, _ = _provider_with(["[]"])
    assert asyncio.run(provider.verify_claims(TRANSCRIPT, {})) == []


# ============================================ Bug 2 — backend fail-closed boundary


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("approved", "approved"),
        ("Approved", "approved"),
        ("  approved\n", "approved"),
        ("Unapproved", "unapproved"),
        ("FORBIDDEN", "forbidden"),
        ("unsupported", "unapproved"),
        ("random-verdict", "unapproved"),
        ("", "unapproved"),
        (None, "unapproved"),
        ("approved?", "unapproved"),
    ],
)
def test_fail_closed_verdict(raw, expected):
    assert fail_closed_verdict(raw) == expected


def test_canonical_verdict_is_strict():
    assert canonical_verdict(" FORBIDDEN ") == "forbidden"
    assert canonical_verdict("unsupported") is None
    assert canonical_verdict("") is None


def _score_session(monkeypatch, *, breakdown, claims=(), critical_errors=()):
    """Runs one session through scoring with the stub scorer replaced — the
    provider-level validation is bypassed on purpose, so these tests exercise
    the backend safety boundary on its own."""
    import app.main as main

    async def verify_claims(transcript, kb):
        return [dict(c) for c in claims]

    async def score(transcript, rubric, claim_checks):
        return {
            "breakdown": [dict(b) for b in breakdown],
            "critical_errors": [dict(e) for e in critical_errors],
            "feedback": {"summary": "s", "strengths": [], "growth_areas": [], "better_examples": [], "next_skill": None},
        }

    monkeypatch.setattr(main.scoring_provider, "verify_claims", verify_claims)
    monkeypatch.setattr(main.scoring_provider, "score", score)
    manager = login("manager2")
    session_id = manager.post("/sessions", json={"scenario_id": SCENARIO}).json()["id"]
    manager.post(f"/sessions/{session_id}/turns", json={"text": "Добрый день!"})
    manager.post(f"/sessions/{session_id}/finish")
    assert manager.post(f"/sessions/{session_id}/score-run").json()["status"] == "finished"
    return manager.get(f"/sessions/{session_id}/score").json()


def _uniform(percent):
    return [{"criterion_id": c, "score": percent, "max": 100} for c in CRITERIA]


def _claim(verdict, text="лимит 500 000", turn=1):
    return {"claim_text": text, "turn_index": turn, "verdict": verdict, "matched_entry_id": None, "reason": "причина"}


@pytest.mark.parametrize("raw", ["unsupported", "random-verdict", "", "Неизвестно"])
def test_unknown_verdict_cannot_bypass_the_cap(server, monkeypatch, raw):
    result = _score_session(monkeypatch, breakdown=_uniform(90), claims=[_claim(raw)])
    assert result["total"] == 60
    assert [c["verdict"] for c in result["claim_checks"]] == ["unapproved"]
    assert result["cap_reason"]["triggers"][0]["verdict"] == "unapproved"


def test_forbidden_behaviour_unchanged(server, monkeypatch):
    result = _score_session(monkeypatch, breakdown=_uniform(90), claims=[_claim("FORBIDDEN")])
    assert result["total"] == 60
    assert result["claim_checks"][0]["verdict"] == "forbidden"
    assert result["cap_reason"]["triggers"][0]["verdict"] == "forbidden"


def test_approved_claim_does_not_cap(server, monkeypatch):
    result = _score_session(monkeypatch, breakdown=_uniform(90), claims=[_claim(" Approved ")])
    assert result["total"] == 90
    assert result["claim_checks"][0]["verdict"] == "approved"
    assert result["cap_reason"] is None


def test_persisted_claims_are_canonical_and_complete(server, monkeypatch):
    claims = [_claim("Approved", "факт 1", 1), _claim("UNAPPROVED", "условие 2", 3), _claim("Forbidden ", "гарантия 3", 5)]
    result = _score_session(monkeypatch, breakdown=_uniform(50), claims=claims)
    stored = sorted(result["claim_checks"], key=lambda c: c["turn_index"])
    assert [(c["turn_index"], c["claim_text"], c["verdict"], c["reason"]) for c in stored] == [
        (1, "факт 1", "approved", "причина"),
        (3, "условие 2", "unapproved", "причина"),
        (5, "гарантия 3", "forbidden", "причина"),
    ]


# ============================================ Bug 3 — /products visibility

SECRET_NAME = "SECRET_DRAFT_PRODUCT_NAME_123"
SECRET_SEGMENT = "SECRET_DRAFT_SEGMENT_456"


@pytest.fixture
def draft_only_product(server):
    product_id = f"p1b_{uuid.uuid4().hex[:8]}"
    data = {
        "id": product_id,
        "name": SECRET_NAME,
        "segment": SECRET_SEGMENT,
        "approved_facts": [{"id": "fact_1", "text": "Проверенный тестовый факт."}],
    }
    response = login("product1").post(f"/admin/kb/{product_id}/versions", json={"version": "1.0.0", "data": data})
    assert response.status_code == 200, response.text
    return product_id


@pytest.mark.parametrize("username", ["manager1", "lead1"])
def test_draft_only_product_hidden_from_manager_and_lead(server, draft_only_product, username):
    response = login(username).get("/products")
    assert response.status_code == 200
    assert SECRET_NAME not in response.text
    assert SECRET_SEGMENT not in response.text
    assert draft_only_product not in response.text


@pytest.mark.parametrize("username", ["trainer1", "product1", "compliance1", "admin"])
def test_content_roles_still_see_draft_only_product(server, draft_only_product, username):
    products = {p["id"]: p for p in login(username).get("/products").json()}
    assert products[draft_only_product] == {"id": draft_only_product, "name": SECRET_NAME, "segment": SECRET_SEGMENT}


def test_product_appears_once_its_kb_is_published(server, draft_only_product):
    assert login("compliance1").post(
        f"/admin/kb/{draft_only_product}/versions/1.0.0/status", json={"status": "approved"}
    ).status_code == 200
    assert login("product1").post(
        f"/admin/kb/{draft_only_product}/versions/1.0.0/status", json={"status": "published"}
    ).status_code == 200
    for username in ("manager1", "lead1"):
        ids = [p["id"] for p in login(username).get("/products").json()]
        assert draft_only_product in ids


def test_published_products_unchanged_and_seed_drafts_hidden(server):
    """merchant_onboarding (published KB) stays visible; the seeded draft-only
    products (РКО, payroll, loan) are no longer listed for managers."""
    ids = {p["id"] for p in login("manager1").get("/products").json()}
    assert "merchant_onboarding" in ids
    assert not ids & {"rko", "payroll_project", "business_loan"}


def test_lead_dashboard_still_loads(server):
    assert login("lead1").get("/dashboard/data").status_code == 200
