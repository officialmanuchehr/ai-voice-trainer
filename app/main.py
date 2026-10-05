import asyncio
import base64
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, inspect, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import session_rows
from app.audit import audit
from app.auth import BasicAuthMiddleware
from app.client_generator import briefing, generate_client
from app.config import settings
from app.constants import STT_VOCABULARY
from app.content import published_kb, session_content, topic_list
from app.database import Base, SessionLocal, engine
from app.models import ClaimCheck, Feedback, KnowledgeBase, Product, Scenario, ScenarioVersion, Score, User
from app.models import Session as SessionModel
from app.models import TranscriptTurn
from app.prompts import build_client_system_prompt
from app.providers.factory import get_dialog_provider, get_scoring_provider, get_stt_provider, get_tts_provider
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.routers import dashboard as dashboard_router
from app.scoring_math import cap_reason, effective_weights, fail_closed_verdict, finalize
from app.security import CONTENT_VIEW_ROLES, TRAINEE_ROLES, get_current_user, require_roles
from app.seed_loader import list_rubrics, load_rubric, load_seed

dialog_provider = get_dialog_provider()
tts_provider = get_tts_provider()
stt_provider = get_stt_provider()
scoring_provider = get_scoring_provider()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# A session left in "scoring" with a claim timestamp older than this is assumed
# to have a dead worker (serverless function timed out or crashed mid-run) and
# may be re-claimed by a fresh POST /sessions/{id}/score-run.
_SCORING_CLAIM_TTL = timedelta(minutes=10)

# Hard cap on one scoring run, kept under the Vercel function limit (300s) so a
# slow run ends as "finish_error" the user can retry, instead of the function
# being killed mid-run and the session sitting in "scoring" until the claim TTL.
_SCORING_BUDGET_SECONDS = 270


# (table, column, type, default) — see _add_missing_columns. "TS" and "JSON"
# are resolved per dialect. Defaults only matter for rows that predate the
# column: the one KB snapshot and scenario that existed before versioning were
# the approved, live ones.
_ADDITIVE_COLUMNS = [
    ("sessions", "scoring_error", "TEXT", None),
    ("sessions", "scoring_started_at", "TS", None),
    ("sessions", "user_id", "VARCHAR", None),
    ("sessions", "scenario_version", "INTEGER", None),
    ("sessions", "client_profile", "JSON", None),
    ("knowledge_base", "status", "VARCHAR", "'published'"),
    ("knowledge_base", "author", "VARCHAR", None),
    ("knowledge_base", "updated_at", "TS", None),
    ("knowledge_base", "approved_by", "VARCHAR", None),
    ("knowledge_base", "published_at", "TS", None),
    ("knowledge_base", "notes", "TEXT", None),
    ("scenarios", "title", "VARCHAR", None),
    ("scenarios", "published_version", "INTEGER", None),
    ("transcript_turns", "latency_ms", "INTEGER", None),
    ("scores", "dispute_comment", "TEXT", None),
    ("scores", "disputed_at", "TS", None),
    ("feedback", "next_skill", "TEXT", None),
]


def _add_missing_columns(sync_conn) -> None:
    """create_all only creates missing tables — it never alters a table that
    already exists, so a new column on an existing model needs its own
    additive migration here. Checked via the dialect-agnostic inspector rather
    than "ADD COLUMN IF NOT EXISTS", which isn't supported on every SQLite
    build (only on SQLite 3.35+, and syntax support varies by distro)."""
    dialect = sync_conn.dialect.name
    types = {
        "TS": "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "TIMESTAMP",
        "JSON": "JSON",
    }
    inspector = inspect(sync_conn)
    existing = {table: {c["name"] for c in inspector.get_columns(table)} for table in {t for t, *_ in _ADDITIVE_COLUMNS}}
    for table, column, col_type, default in _ADDITIVE_COLUMNS:
        if column in existing[table]:
            continue
        ddl = f"ALTER TABLE {table} ADD COLUMN {column} {types.get(col_type, col_type)}"
        if default is not None:
            ddl += f" DEFAULT {default}"
        sync_conn.execute(text(ddl))


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
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(dashboard_router.router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# HTML pages are served without a login check; each page's JS calls /auth/me
# and redirects to /login on 401. All data comes from the role-checked API.
_PAGES = {"/": "index.html", "/login": "login.html", "/dashboard": "dashboard.html", "/admin": "admin.html", "/session": "session.html"}


def _page(filename: str):
    async def handler():
        return FileResponse(str(STATIC_DIR / filename))

    return handler


for _path, _file in _PAGES.items():
    app.add_api_route(_path, _page(_file), methods=["GET"], include_in_schema=False)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/products")
async def list_products(user: User = Depends(get_current_user)):
    """Content roles see every product. Everyone else sees only products with
    a published knowledge base: a draft-only product's name and segment are
    unapproved KB content, and even its existence isn't shown."""
    async with SessionLocal() as db:
        query = select(Product)
        if user.role not in CONTENT_VIEW_ROLES:
            published = select(KnowledgeBase.product_id).where(KnowledgeBase.status == "published")
            query = query.where(Product.id.in_(published))
        result = await db.execute(query)
        products = result.scalars().all()
        return [{"id": p.id, "name": p.name, "segment": p.segment} for p in products]


@app.get("/rubric")
async def get_rubrics(user: User = Depends(get_current_user)):
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "criteria": [{"id": c["id"], "name": c["name"], "weight": c["weight"], "checks": c.get("checks")} for c in r["criteria"]],
        }
        for r in list_rubrics()
    ]


@app.get("/kb/{product_id}")
async def get_kb(product_id: str, user: User = Depends(require_roles(*CONTENT_VIEW_ROLES))):
    async with SessionLocal() as db:
        kb = await published_kb(db, product_id)
        if kb is None:
            raise HTTPException(status_code=404, detail="no published knowledge base for product")
        return {"version": kb.version, "data": kb.data}


@app.get("/scenarios")
async def list_scenarios(user: User = Depends(require_roles(*TRAINEE_ROLES))):
    """Published scenarios whose product has a published knowledge base — the
    catalogue a manager picks from. Only the briefing part of the client
    profile is exposed; pains, hidden needs and objections stay hidden."""
    async with SessionLocal() as db:
        published_products = set(
            (await db.execute(select(KnowledgeBase.product_id).where(KnowledgeBase.status == "published"))).scalars()
        )
        products = {p.id: p.name for p in (await db.execute(select(Product))).scalars()}
        result = await db.execute(select(Scenario).where(Scenario.published_version.is_not(None)))
        scenarios = [s for s in result.scalars().all() if s.product_id in published_products]
        versions = {
            (v.scenario_id, v.version): v
            for v in (
                await db.execute(select(ScenarioVersion).where(ScenarioVersion.scenario_id.in_([s.id for s in scenarios])))
            ).scalars()
        }
        items = []
        for s in scenarios:
            data = versions[(s.id, s.published_version)].data
            items.append(
                {
                    "id": s.id,
                    "version": s.published_version,
                    "title": data.get("title") or s.id,
                    "product_id": s.product_id,
                    "product_name": products.get(s.product_id, s.product_id),
                    "difficulty": s.difficulty,
                    "goal": s.goal,
                    "learning_goal": (data.get("config") or {}).get("learning_goal", ""),
                    "topics": topic_list(data.get("topics")),
                    "briefing": briefing(s.client_profile),
                }
            )
        order = {"easy": 0, "medium": 1, "hard": 2}
        items.sort(key=lambda i: (i["product_name"], order.get(i["difficulty"], 9)))
        return items


@app.get("/me/sessions")
async def my_sessions(user: User = Depends(get_current_user)):
    async with SessionLocal() as db:
        return await session_rows(db, [user.id])


async def _load_session(db: AsyncSession, session_id: str, user: User, write: bool = False) -> SessionModel:
    """Owner may do anything with their session. Read-only access: admins, and
    a sales lead for sessions of managers on their own team (PRD §14). The
    aggregate-only roles never see individual transcripts."""
    session = await db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.user_id == user.id:
        return session
    if write:
        # Legacy sessions created before users existed can be finished by an admin.
        if session.user_id is None and user.role == "admin":
            return session
        raise HTTPException(status_code=403, detail="это чужая сессия")
    if user.role == "admin":
        return session
    if user.role == "sales_lead" and user.team_id is not None and session.user_id:
        owner = await db.get(User, session.user_id)
        if owner is not None and owner.team_id == user.team_id:
            return session
    raise HTTPException(status_code=403, detail="нет доступа к этой сессии")


class CreateSessionRequest(BaseModel):
    scenario_id: str


class TurnRequest(BaseModel):
    text: str


@app.post("/sessions")
async def create_session(body: CreateSessionRequest, user: User = Depends(require_roles(*TRAINEE_ROLES))):
    """Binds the new session to the scenario's published version and the
    product's published KB version, and generates this session's AI-client."""
    async with SessionLocal() as db:
        scenario = await db.get(Scenario, body.scenario_id)
        if scenario is None or scenario.published_version is None:
            raise HTTPException(status_code=404, detail="scenario not found or not published")
        version = await db.scalar(
            select(ScenarioVersion).where(
                ScenarioVersion.scenario_id == scenario.id,
                ScenarioVersion.version == scenario.published_version,
            )
        )
        content = version.data

        kb = await published_kb(db, content["product_id"])
        if kb is None:
            raise HTTPException(status_code=409, detail="у продукта нет опубликованной базы знаний")

        profile = generate_client(content["client_profile"])
        session = SessionModel(
            scenario_id=scenario.id,
            scenario_version=version.version,
            kb_version=kb.version,
            rubric_id=content["rubric_id"],
            user_id=user.id,
            client_profile=profile,
            status="active",
        )
        db.add(session)
        await db.flush()
        audit(
            db,
            user,
            "session.start",
            "session",
            session.id,
            {"scenario_id": scenario.id, "scenario_version": version.version, "kb_version": kb.version},
        )
        await db.commit()
        await db.refresh(session)

        return {
            "id": session.id,
            "scenario_id": session.scenario_id,
            "scenario_version": session.scenario_version,
            "title": content.get("title"),
            "goal": content["goal"],
            "learning_goal": (content.get("config") or {}).get("learning_goal", ""),
            "difficulty": content["difficulty"],
            "product_id": content["product_id"],
            "briefing": briefing(profile),
            "kb_version": session.kb_version,
            "rubric_id": session.rubric_id,
            "status": session.status,
            "started_at": session.started_at.isoformat(),
        }


async def _process_manager_turn(db: AsyncSession, session_id: str, manager_text: str, user: User) -> dict:
    """Shared logic behind the text turn (/turns) and voice turn (/voice-turn)
    endpoints: validate the session, persist the manager's line, build the
    AI-client's system prompt from the session's bound kb_version, and get
    its reply. Returns a plain dict, not an HTTP response, so both endpoints
    can shape the response differently (voice-turn also attaches audio)."""
    session = await _load_session(db, session_id, user, write=True)
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"session is not active (status={session.status})")
    if not manager_text.strip():
        raise HTTPException(status_code=400, detail="пустая реплика — речь не распознана")

    content, kb = await session_content(db, session)
    client_profile = session.client_profile or content["client_profile"]

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

    system_prompt = build_client_system_prompt(client_profile, kb.data, content["difficulty"])

    started = time.perf_counter()
    ai_text = await dialog_provider.respond(system_prompt, messages)
    latency_ms = round((time.perf_counter() - started) * 1000)

    ai_turn = TranscriptTurn(
        session_id=session_id,
        turn_index=next_index + 1,
        role="ai_client",
        text=ai_text,
        latency_ms=latency_ms,
    )
    db.add(ai_turn)
    await db.commit()

    return {
        "manager_turn_index": next_index,
        "manager_text": manager_text,
        "ai_client_turn_index": next_index + 1,
        "ai_client_text": ai_text,
        "latency_ms": latency_ms,
    }


@app.post("/sessions/{session_id}/turns")
async def post_turn(session_id: str, body: TurnRequest, user: User = Depends(get_current_user)):
    async with SessionLocal() as db:
        return await _process_manager_turn(db, session_id, body.text, user)


@app.post("/sessions/{session_id}/voice-turn")
async def post_voice_turn(session_id: str, audio: UploadFile = File(...), user: User = Depends(get_current_user)):
    async with SessionLocal() as db:
        # Fail fast before spending an STT call on someone else's session.
        await _load_session(db, session_id, user, write=True)
    audio_bytes = await audio.read()
    try:
        manager_text = await stt_provider.transcribe(audio_bytes, "ru", STT_VOCABULARY)
    finally:
        del audio_bytes  # never touches disk or the DB; discarded right after transcription

    async with SessionLocal() as db:
        result = await _process_manager_turn(db, session_id, manager_text, user)

    ai_audio = await tts_provider.synthesize(result["ai_client_text"], "ru")
    result["ai_client_audio_base64"] = base64.b64encode(ai_audio).decode("ascii")
    return result


@app.get("/sessions/{session_id}/transcript")
async def get_transcript(session_id: str, user: User = Depends(get_current_user)):
    async with SessionLocal() as db:
        session = await _load_session(db, session_id, user)

        result = await db.execute(
            select(TranscriptTurn).where(TranscriptTurn.session_id == session_id).order_by(TranscriptTurn.turn_index)
        )
        turns = result.scalars().all()
        return {
            "session_id": session_id,
            "kb_version": session.kb_version,
            "status": session.status,
            "turns": [
                {"turn_index": t.turn_index, "role": t.role, "text": t.text, "latency_ms": t.latency_ms} for t in turns
            ],
        }


@app.get("/sessions/{session_id}/turns/{turn_index}/audio")
async def get_turn_audio(session_id: str, turn_index: int, user: User = Depends(get_current_user)):
    async with SessionLocal() as db:
        await _load_session(db, session_id, user)
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
async def finish_session(session_id: str, user: User = Depends(get_current_user)):
    """Marks the session ready for scoring and returns immediately. The actual
    scoring — two sequential Claude calls, 60s+ — is done by a separate call to
    POST /sessions/{id}/score-run that the client fires without awaiting, then
    polls GET /sessions/{id}/score for the result. Splitting it keeps every
    request short: one long synchronous request is exactly what mobile
    networks/proxies were killing in production (client closed at 30s, losing a
    finished result)."""
    async with SessionLocal() as db:
        session = await _load_session(db, session_id, user, write=True)
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
async def score_run(session_id: str, user: User = Depends(get_current_user)):
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
        await _load_session(db, session_id, user, write=True)
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

    try:
        await asyncio.wait_for(_run_scoring(session_id), timeout=_SCORING_BUDGET_SECONDS)
    except TimeoutError:
        # wait_for cancelled _run_scoring, so its own error handler never ran.
        async with SessionLocal() as db:
            session = await db.get(SessionModel, session_id)
            session.status = "finish_error"
            session.scoring_error = f"оценка не уложилась в {_SCORING_BUDGET_SECONDS} с — попробуйте ещё раз"
            await db.commit()

    async with SessionLocal() as db:
        session = await db.get(SessionModel, session_id)
    return {"session_id": session_id, "status": session.status, "claimed": True}


async def _run_scoring(session_id: str) -> None:
    async with SessionLocal() as db:
        session = await db.get(SessionModel, session_id)
        try:
            content, kb = await session_content(db, session)
            config = content.get("config") or {}

            turns_result = await db.execute(
                select(TranscriptTurn)
                .where(TranscriptTurn.session_id == session_id)
                .order_by(TranscriptTurn.turn_index)
            )
            turns = turns_result.scalars().all()
            transcript = [{"turn_index": t.turn_index, "role": t.role, "text": t.text} for t in turns]

            rubric = load_rubric(session.rubric_id)
            # Scenario context rides along inside the rubric JSON the scorer
            # already receives; it informs feedback, never product truth.
            rubric_for_scorer = {
                **rubric,
                "scenario_context": {
                    "goal": content["goal"],
                    "difficulty": content["difficulty"],
                    "learning_goal": config.get("learning_goal", ""),
                    "good_examples": config.get("good_examples", []),
                    "feedback_hints": config.get("feedback_hints", []),
                },
            }

            claim_checks = await scoring_provider.verify_claims(transcript, kb.data)
            # Safety boundary independent of the provider: an unrecognised
            # verdict is stored and scored as "unapproved", never as safe.
            claim_checks = [{**claim, "verdict": fail_closed_verdict(claim.get("verdict"))} for claim in claim_checks]
            for claim in claim_checks:
                db.add(
                    ClaimCheck(
                        session_id=session_id,
                        turn_index=claim.get("turn_index", 0),
                        claim_text=claim.get("claim_text", ""),
                        verdict=claim["verdict"],
                        matched_entry_id=claim.get("matched_entry_id"),
                        reason=claim.get("reason"),
                    )
                )

            result = await scoring_provider.score(transcript, rubric_for_scorer, claim_checks)
            finalize(result, rubric, claim_checks, config.get("criteria_weights"))

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
                    next_skill=feedback.get("next_skill"),
                )
            )

            session.status = "finished"
            session.ended_at = datetime.now(timezone.utc)
            trainee = await db.get(User, session.user_id) if session.user_id else None
            audit(
                db,
                trainee,
                "session.scored",
                "session",
                session_id,
                {
                    "scenario_id": session.scenario_id,
                    "scenario_version": session.scenario_version or 1,
                    "kb_version": session.kb_version,
                    "total": result["total"],
                    "critical_errors": [e.get("type") for e in result.get("critical_errors", [])],
                },
            )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            session = await db.get(SessionModel, session_id)
            session.status = "finish_error"
            session.scoring_error = str(exc)
            await db.commit()


@app.get("/sessions/{session_id}/score")
async def get_score(session_id: str, user: User = Depends(get_current_user)):
    async with SessionLocal() as db:
        session = await _load_session(db, session_id, user)

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

        # Same inputs finalize() used when scoring: the rubric plus the bound
        # scenario version's weight overrides.
        content, _ = await session_content(db, session)
        weights = effective_weights(load_rubric(session.rubric_id), (content.get("config") or {}).get("criteria_weights"))
        cap = cap_reason(
            {"breakdown": score.breakdown, "critical_errors": score.critical_errors},
            [{"verdict": c.verdict, "claim_text": c.claim_text, "turn_index": c.turn_index, "reason": c.reason} for c in claim_checks],
            weights,
        )

        return {
            "session_id": session_id,
            "status": "finished",
            "kb_version": session.kb_version,
            "scenario_version": session.scenario_version or 1,
            "rubric_id": session.rubric_id,
            "own": session.user_id == user.id,
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
            "cap_reason": cap,
            "breakdown": score.breakdown,
            "critical_errors": score.critical_errors,
            "feedback": {
                "summary": feedback.summary,
                "strengths": feedback.strengths,
                "growth_areas": feedback.growth_areas,
                "better_examples": feedback.better_examples,
                "next_skill": feedback.next_skill,
            },
            "dispute": {"comment": score.dispute_comment, "at": score.disputed_at.isoformat()} if score.disputed_at else None,
        }


class DisputeRequest(BaseModel):
    comment: str


@app.post("/sessions/{session_id}/dispute")
async def dispute_score(session_id: str, body: DisputeRequest, user: User = Depends(get_current_user)):
    """The manager contests their score. Recorded for the training team to
    review; the score itself is not changed automatically."""
    comment = body.comment.strip()
    if not comment:
        raise HTTPException(status_code=400, detail="опишите, с чем вы не согласны")
    async with SessionLocal() as db:
        session = await _load_session(db, session_id, user, write=True)
        score = await db.scalar(select(Score).where(Score.session_id == session.id))
        if score is None:
            raise HTTPException(status_code=400, detail="сессия ещё не оценена")
        score.dispute_comment = comment[:2000]
        score.disputed_at = datetime.now(timezone.utc)
        audit(db, user, "score.dispute", "session", session.id, {"total": score.total})
        await db.commit()
    return {"status": "ok"}
