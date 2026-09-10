import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, inspect, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import BasicAuthMiddleware
from app.config import settings
from app.constants import STT_VOCABULARY
from app.database import Base, SessionLocal, engine
from app.models import ClaimCheck, Feedback, KnowledgeBase, Product, Scenario, Score
from app.models import Session as SessionModel
from app.models import TranscriptTurn
from app.prompts import build_client_system_prompt
from app.providers.factory import get_dialog_provider, get_scoring_provider, get_stt_provider, get_tts_provider
from app.seed_loader import load_rubric, load_seed

dialog_provider = get_dialog_provider()
tts_provider = get_tts_provider()
stt_provider = get_stt_provider()
scoring_provider = get_scoring_provider()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# A session left in "scoring" with a claim timestamp older than this is assumed
# to have a dead worker (serverless function timed out or crashed mid-run) and
# may be re-claimed by a fresh POST /sessions/{id}/score-run.
_SCORING_CLAIM_TTL = timedelta(minutes=10)


def _add_missing_columns(sync_conn) -> None:
    """create_all only creates missing tables — it never alters a table that
    already exists, so a new column on an existing model needs its own
    additive migration here. Checked via the dialect-agnostic inspector rather
    than "ADD COLUMN IF NOT EXISTS", which isn't supported on every SQLite
    build (only on SQLite 3.35+, and syntax support varies by distro)."""
    dialect = sync_conn.dialect.name
    ts_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "TIMESTAMP"
    columns = {c["name"] for c in inspect(sync_conn).get_columns("sessions")}
    if "scoring_error" not in columns:
        sync_conn.execute(text("ALTER TABLE sessions ADD COLUMN scoring_error TEXT"))
    if "scoring_started_at" not in columns:
        sync_conn.execute(text(f"ALTER TABLE sessions ADD COLUMN scoring_started_at {ts_type}"))


async def init_db() -> None:
    """Create tables, apply additive column migrations, load seed data.
    Idempotent. Runs from lifespan for local dev and single-instance containers;
    on serverless (Vercel, settings.auto_init_db=false) run scripts/init_db.py
    once after deploy instead — dozens of cold starts racing on CREATE TABLE /
    seed inserts is not worth defending against per request."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)

    async with SessionLocal() as db:
        await load_seed(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_init_db:
        await init_db()
    yield


app = FastAPI(title="AI Voice Trainer", lifespan=lifespan)
app.add_middleware(BasicAuthMiddleware)


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/products")
async def list_products():
    async with SessionLocal() as db:
        result = await db.execute(select(Product))
        products = result.scalars().all()
        return [{"id": p.id, "name": p.name, "segment": p.segment} for p in products]


@app.get("/kb/{product_id}")
async def get_kb(product_id: str):
    async with SessionLocal() as db:
        result = await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.product_id == product_id)
            .order_by(KnowledgeBase.id.desc())
        )
        kb = result.scalars().first()
        if kb is None:
            return {"error": "not found"}
        return {"version": kb.version, "data": kb.data}


@app.get("/scenarios")
async def list_scenarios():
    async with SessionLocal() as db:
        result = await db.execute(select(Scenario))
        scenarios = result.scalars().all()
        return [
            {
                "id": s.id,
                "product_id": s.product_id,
                "difficulty": s.difficulty,
                "goal": s.goal,
                "rubric_id": s.rubric_id,
                "client_profile": s.client_profile,
            }
            for s in scenarios
        ]


class CreateSessionRequest(BaseModel):
    scenario_id: str


class TurnRequest(BaseModel):
    text: str


@app.post("/sessions")
async def create_session(body: CreateSessionRequest):
    async with SessionLocal() as db:
        scenario = await db.get(Scenario, body.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="scenario not found")

        kb = await db.scalar(
            select(KnowledgeBase)
            .where(KnowledgeBase.product_id == scenario.product_id)
            .order_by(KnowledgeBase.id.desc())
        )
        if kb is None:
            raise HTTPException(status_code=500, detail="no knowledge base for product")

        session = SessionModel(
            scenario_id=scenario.id,
            kb_version=kb.version,
            rubric_id=scenario.rubric_id,
            status="active",
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        return {
            "id": session.id,
            "scenario_id": session.scenario_id,
            "kb_version": session.kb_version,
            "rubric_id": session.rubric_id,
            "status": session.status,
            "started_at": session.started_at.isoformat(),
        }


async def _process_manager_turn(db: AsyncSession, session_id: str, manager_text: str) -> dict:
    """Shared logic behind the text turn (/turns) and voice turn (/voice-turn)
    endpoints: validate the session, persist the manager's line, build the
    AI-client's system prompt from the session's bound kb_version, and get
    its reply. Returns a plain dict, not an HTTP response, so both endpoints
    can shape the response differently (voice-turn also attaches audio)."""
    session = await db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"session is not active (status={session.status})")

    scenario = await db.get(Scenario, session.scenario_id)

    kb = await db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.product_id == scenario.product_id,
            KnowledgeBase.version == session.kb_version,
        )
    )
    if kb is None:
        raise HTTPException(status_code=500, detail="knowledge base snapshot missing for session.kb_version")

    max_index = await db.scalar(
        select(func.max(TranscriptTurn.turn_index)).where(TranscriptTurn.session_id == session_id)
    )
    next_index = (max_index or 0) + 1

    manager_turn = TranscriptTurn(
        session_id=session_id,
        turn_index=next_index,
        role="manager",
        text=manager_text,
    )
    db.add(manager_turn)
    await db.flush()

    history_result = await db.execute(
        select(TranscriptTurn).where(TranscriptTurn.session_id == session_id).order_by(TranscriptTurn.turn_index)
    )
    history = history_result.scalars().all()
    messages = [{"role": t.role, "text": t.text} for t in history]

    system_prompt = build_client_system_prompt(scenario.client_profile, kb.data)

    ai_text = await dialog_provider.respond(system_prompt, messages)

    ai_turn = TranscriptTurn(
        session_id=session_id,
        turn_index=next_index + 1,
        role="ai_client",
        text=ai_text,
    )
    db.add(ai_turn)
    await db.commit()

    return {
        "manager_turn_index": next_index,
        "manager_text": manager_text,
        "ai_client_turn_index": next_index + 1,
        "ai_client_text": ai_text,
    }


@app.post("/sessions/{session_id}/turns")
async def post_turn(session_id: str, body: TurnRequest):
    async with SessionLocal() as db:
        return await _process_manager_turn(db, session_id, body.text)


@app.post("/sessions/{session_id}/voice-turn")
async def post_voice_turn(session_id: str, audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    try:
        manager_text = await stt_provider.transcribe(audio_bytes, "ru", STT_VOCABULARY)
    finally:
        del audio_bytes  # never touches disk or the DB; discarded right after transcription

    async with SessionLocal() as db:
        result = await _process_manager_turn(db, session_id, manager_text)

    ai_audio = await tts_provider.synthesize(result["ai_client_text"], "ru")
    result["ai_client_audio_base64"] = base64.b64encode(ai_audio).decode("ascii")
    return result


@app.get("/sessions/{session_id}/transcript")
async def get_transcript(session_id: str):
    async with SessionLocal() as db:
        session = await db.get(SessionModel, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")

        result = await db.execute(
            select(TranscriptTurn).where(TranscriptTurn.session_id == session_id).order_by(TranscriptTurn.turn_index)
        )
        turns = result.scalars().all()
        return {
            "session_id": session_id,
            "kb_version": session.kb_version,
            "status": session.status,
            "turns": [{"turn_index": t.turn_index, "role": t.role, "text": t.text} for t in turns],
        }


@app.get("/sessions/{session_id}/turns/{turn_index}/audio")
async def get_turn_audio(session_id: str, turn_index: int):
    async with SessionLocal() as db:
        turn = await db.scalar(
            select(TranscriptTurn).where(
                TranscriptTurn.session_id == session_id,
                TranscriptTurn.turn_index == turn_index,
            )
        )
        if turn is None:
            raise HTTPException(status_code=404, detail="turn not found")
        if turn.role != "ai_client":
            raise HTTPException(status_code=400, detail="audio is only available for ai_client turns")
        text = turn.text

    audio_bytes = await tts_provider.synthesize(text, "ru")
    return Response(content=audio_bytes, media_type="audio/mpeg")


@app.post("/sessions/{session_id}/finish")
async def finish_session(session_id: str):
    """Marks the session ready for scoring and returns immediately. The actual
    scoring — two sequential Claude calls, 60s+ — is done by a separate call to
    POST /sessions/{id}/score-run that the client fires without awaiting, then
    polls GET /sessions/{id}/score for the result. Splitting it keeps every
    request short: one long synchronous request is exactly what mobile
    networks/proxies were killing in production (client closed at 30s, losing a
    finished result)."""
    async with SessionLocal() as db:
        session = await db.get(SessionModel, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        if session.status not in ("active", "finish_error"):
            raise HTTPException(status_code=400, detail=f"session is not active (status={session.status})")

        turns_count = await db.scalar(
            select(func.count()).select_from(TranscriptTurn).where(TranscriptTurn.session_id == session_id)
        )
        if not turns_count:
            raise HTTPException(status_code=400, detail="session has no turns to score")

        session.status = "scoring"
        session.scoring_error = None
        session.scoring_started_at = None
        await db.commit()

    return {"session_id": session_id, "status": "scoring"}


@app.post("/sessions/{session_id}/score-run")
async def score_run(session_id: str):
    """Runs scoring synchronously (60s+) and returns the terminal status. The
    client fires this once after /finish and does NOT wait on it — if the
    connection drops, the server still runs to completion (neither Vercel's
    serverless functions nor uvicorn cancel a handler on client disconnect),
    and the client reads the outcome from GET /sessions/{id}/score polling.

    Idempotent by design: the claiming UPDATE only matches a session that is
    still "scoring" and either unclaimed or whose claim has gone stale (worker
    died mid-run), so a duplicate call or a post-crash retry does the right
    thing instead of scoring twice in parallel."""
    now = datetime.now(timezone.utc)
    stale_before = now - _SCORING_CLAIM_TTL
    async with SessionLocal() as db:
        result = await db.execute(
            update(SessionModel)
            .where(
                SessionModel.id == session_id,
                SessionModel.status == "scoring",
                or_(
                    SessionModel.scoring_started_at.is_(None),
                    SessionModel.scoring_started_at < stale_before,
                ),
            )
            .values(scoring_started_at=now)
        )
        await db.commit()
        claimed = result.rowcount == 1

        if not claimed:
            session = await db.get(SessionModel, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            return {"session_id": session_id, "status": session.status, "claimed": False}

    await _run_scoring(session_id)

    async with SessionLocal() as db:
        session = await db.get(SessionModel, session_id)
    return {"session_id": session_id, "status": session.status, "claimed": True}


async def _run_scoring(session_id: str) -> None:
    async with SessionLocal() as db:
        session = await db.get(SessionModel, session_id)
        try:
            scenario = await db.get(Scenario, session.scenario_id)

            kb = await db.scalar(
                select(KnowledgeBase).where(
                    KnowledgeBase.product_id == scenario.product_id,
                    KnowledgeBase.version == session.kb_version,
                )
            )
            if kb is None:
                raise RuntimeError("knowledge base snapshot missing for session.kb_version")

            turns_result = await db.execute(
                select(TranscriptTurn)
                .where(TranscriptTurn.session_id == session_id)
                .order_by(TranscriptTurn.turn_index)
            )
            turns = turns_result.scalars().all()
            transcript = [{"turn_index": t.turn_index, "role": t.role, "text": t.text} for t in turns]

            rubric = load_rubric(session.rubric_id)

            claim_checks = await scoring_provider.verify_claims(transcript, kb.data)
            for claim in claim_checks:
                db.add(
                    ClaimCheck(
                        session_id=session_id,
                        turn_index=claim.get("turn_index", 0),
                        claim_text=claim.get("claim_text", ""),
                        verdict=claim.get("verdict", "unapproved"),
                        matched_entry_id=claim.get("matched_entry_id"),
                        reason=claim.get("reason"),
                    )
                )

            result = await scoring_provider.score(transcript, rubric, claim_checks)

            db.add(
                Score(
                    session_id=session_id,
                    rubric_id=session.rubric_id,
                    total=result["total"],
                    breakdown=result["breakdown"],
                    critical_errors=result.get("critical_errors", []),
                )
            )

            feedback = result.get("feedback", {})
            db.add(
                Feedback(
                    session_id=session_id,
                    summary=feedback.get("summary", ""),
                    strengths=feedback.get("strengths", []),
                    growth_areas=feedback.get("growth_areas", []),
                    better_examples=feedback.get("better_examples", []),
                )
            )

            session.status = "finished"
            session.ended_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            session = await db.get(SessionModel, session_id)
            session.status = "finish_error"
            session.scoring_error = str(exc)
            await db.commit()


@app.get("/sessions/{session_id}/score")
async def get_score(session_id: str):
    async with SessionLocal() as db:
        session = await db.get(SessionModel, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")

        if session.status == "scoring":
            return {"session_id": session_id, "status": "scoring"}
        if session.status == "finish_error":
            return {"session_id": session_id, "status": "finish_error", "detail": session.scoring_error}
        if session.status != "finished":
            # e.g. "active" — scoring hasn't been started yet. Not an error: lets the
            # frontend check current state before deciding whether to POST /finish.
            return {"session_id": session_id, "status": session.status}

        score = await db.scalar(select(Score).where(Score.session_id == session_id))
        feedback = await db.scalar(select(Feedback).where(Feedback.session_id == session_id))
        claims_result = await db.execute(select(ClaimCheck).where(ClaimCheck.session_id == session_id))
        claim_checks = claims_result.scalars().all()

        return {
            "session_id": session_id,
            "status": "finished",
            "kb_version": session.kb_version,
            "rubric_id": session.rubric_id,
            "claim_checks": [
                {
                    "turn_index": c.turn_index,
                    "claim_text": c.claim_text,
                    "verdict": c.verdict,
                    "matched_entry_id": c.matched_entry_id,
                    "reason": c.reason,
                }
                for c in claim_checks
            ],
            "total": score.total,
            "breakdown": score.breakdown,
            "critical_errors": score.critical_errors,
            "feedback": {
                "summary": feedback.summary,
                "strengths": feedback.strengths,
                "growth_areas": feedback.growth_areas,
                "better_examples": feedback.better_examples,
            },
        }
