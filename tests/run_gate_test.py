"""Deterministic scoring gate test.

Seeds a session's transcript_turns directly from a fixture file (both manager
and ai_client roles, exactly as recorded), never calling DialogProvider — so
the transcript fed into /finish is byte-identical every run. Only ScoringProvider
(claim-verification + scoring) is exercised, isolating its behavior from the
non-determinism of the AI-client dialogue.

Requires the app server to be running (reads DATABASE_URL from the same .env
to write directly into transcript_turns, then calls /finish over HTTP).

Usage:
    python3 tests/run_gate_test.py tests/fixtures/dialogue_honest.json
    python3 tests/run_gate_test.py tests/fixtures/dialogue_misselling_500k.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import KnowledgeBase, Scenario  # noqa: E402
from app.models import Session as SessionModel  # noqa: E402
from app.models import TranscriptTurn  # noqa: E402

API_BASE = "http://127.0.0.1:8000"


async def seed_session_from_fixture(fixture: dict) -> str:
    """Creates a session bound to the fixture's scenario/kb_version and writes
    the fixture's transcript straight into transcript_turns. DialogProvider is
    never imported or called anywhere in this path."""
    async with SessionLocal() as db:
        scenario = await db.get(Scenario, fixture["scenario_id"])
        if scenario is None:
            raise SystemExit(f"scenario not found in DB: {fixture['scenario_id']}")

        kb = await db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.product_id == fixture["product_id"],
                KnowledgeBase.version == fixture["kb_version"],
            )
        )
        if kb is None:
            raise SystemExit(f"kb snapshot not found: {fixture['product_id']} @ {fixture['kb_version']}")

        session = SessionModel(
            scenario_id=scenario.id,
            kb_version=kb.version,
            rubric_id=fixture["rubric_id"],
            status="active",
        )
        db.add(session)
        await db.flush()

        for turn in fixture["transcript"]:
            db.add(
                TranscriptTurn(
                    session_id=session.id,
                    turn_index=turn["turn_index"],
                    role=turn["role"],
                    text=turn["text"],
                )
            )

        await db.commit()
        return session.id


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fixture_path", help="Path to a tests/fixtures/dialogue_*.json file")
    parser.add_argument("-o", "--out", help="Where to write the full /finish result JSON")
    args = parser.parse_args()

    fixture = json.loads(Path(args.fixture_path).read_text(encoding="utf-8"))

    session_id = await seed_session_from_fixture(fixture)
    print(f"session seeded from fixture (no DialogProvider calls): {session_id}", flush=True)
    print(f"transcript turns written: {len(fixture['transcript'])}", flush=True)

    print("calling /finish + /score-run ...", flush=True)
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(f"{API_BASE}/sessions/{session_id}/finish")
        resp.raise_for_status()
        # Scoring is a separate synchronous call now (see app/main.py): /finish
        # only flips the session to "scoring". /score-run runs the Claude calls
        # and returns when done; the full result is then read from /score.
        resp = await client.post(f"{API_BASE}/sessions/{session_id}/score-run")
        resp.raise_for_status()
        resp = await client.get(f"{API_BASE}/sessions/{session_id}/score")
        resp.raise_for_status()
        result = resp.json()
        if result.get("status") == "finish_error":
            raise SystemExit(f"scoring failed: {result.get('detail')}")

    print(f"total: {result['total']}", flush=True)
    print(f"critical_errors: {len(result.get('critical_errors', []))}", flush=True)
    for ce in result.get("critical_errors", []):
        print(f"  - [{ce['type']}] {ce['quote']}", flush=True)

    out_path = Path(args.out) if args.out else Path("/tmp") / f"gate_test_{Path(args.fixture_path).stem}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"full result written to {out_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
