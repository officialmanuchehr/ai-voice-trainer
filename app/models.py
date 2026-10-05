import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Content lifecycle shared by scenario versions and knowledge-base versions
# (PRD §12): draft -> approved -> published -> archived. Approved and published
# content is immutable — changing it means creating a new draft version.
CONTENT_STATUSES = ("draft", "approved", "published", "archived")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # manager | sales_lead | training | product | compliance | admin (see app/security.py)
    role: Mapped[str] = mapped_column(String, nullable=False)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """Append-only journal (PRD §14 «Журналирование»): who trained on what,
    which scenario/KB version was used, which score and critical errors came
    out, and who changed scenarios, the knowledge base or user access."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class LoginAttempt(Base):
    """One failed login, for throttling (app/login_guard.py). Holds no
    username, IP or password — only an HMAC of (normalised username, client
    IP) — and rows older than the throttle window are purged."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    segment: Mapped[str] = mapped_column(String, nullable=False)

    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="product")


class KnowledgeBase(Base):
    """Immutable snapshot of the knowledge base content for a given version.

    Sessions bind to a specific row here (via kb_version) so that historical
    results stay tied to the content they were trained/scored against, even
    if seed/knowledge_base.json changes later.
    """

    __tablename__ = "knowledge_base"
    __table_args__ = (UniqueConstraint("product_id", "version", name="uq_kb_product_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # One of CONTENT_STATUSES. New sessions bind to the product's single
    # "published" version; only drafts may be edited in place.
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Scenario(Base):
    """A scenario's identity plus a denormalised copy of its currently
    published version (client_profile, difficulty, goal, rubric_id), kept in
    sync on publish. The versioned content itself lives in ScenarioVersion;
    sessions read from there via (scenario_id, scenario_version)."""

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    client_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    difficulty: Mapped[str] = mapped_column(String, nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    # NULL = nothing published: the scenario is invisible to managers.
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    product: Mapped["Product"] = relationship(back_populates="scenarios")


class ScenarioVersion(Base):
    """Immutable-once-approved snapshot of a scenario. `data` holds
    product_id, title, difficulty, goal, rubric_id, client_profile and config
    (learning_goal, criteria_weights, good_examples, feedback_hints)."""

    __tablename__ = "scenario_versions"
    __table_args__ = (UniqueConstraint("scenario_id", "version", name="uq_scenario_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"), nullable=False)
    kb_version: Mapped[str] = mapped_column(String, nullable=False)
    rubric_id: Mapped[str] = mapped_column(String, nullable=False)
    # NULL only for sessions created before users existed.
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # NULL only for sessions created before scenario versioning (= version 1).
    scenario_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The concrete AI-client generated for this session from the scenario's
    # base profile + randomised variants (app/client_generator.py). Stored so
    # the dialogue stays consistent across turns and the session is auditable.
    client_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    # status transitions: active -> scoring -> finished | finish_error (finish_error can
    # retry back to scoring). Scoring runs as a FastAPI BackgroundTask after /finish
    # returns, since the two sequential Claude calls behind it can take over a minute —
    # long enough that mobile networks/proxies kill an open request before it completes.
    scoring_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set by POST /sessions/{id}/score-run when it claims this session for
    # scoring. Lets a duplicate call or a post-crash retry tell "already being
    # scored" (recent timestamp) from "worker died mid-run, safe to re-run"
    # (timestamp older than _SCORING_CLAIM_TTL). NULL until first claimed.
    scoring_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # manager | ai_client
    text: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # ai_client turns only: how long the DialogProvider took to answer (PRD §14,
    # target 2–4 s). STT/TTS time is not included.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ClaimCheck(Base):
    __tablename__ = "claim_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)  # approved | unapproved | forbidden
    matched_entry_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False, unique=True)
    rubric_id: Mapped[str] = mapped_column(String, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    breakdown: Mapped[list] = mapped_column(JSON, nullable=False)
    critical_errors: Mapped[list] = mapped_column(JSON, nullable=False)
    # Manager's objection to the score (PRD §16: «доля оценок, по которым
    # менеджер отправил возражение»).
    dispute_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    disputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False, unique=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list] = mapped_column(JSON, nullable=False)
    growth_areas: Mapped[list] = mapped_column(JSON, nullable=False)
    better_examples: Mapped[list] = mapped_column(JSON, nullable=False)
    next_skill: Mapped[str | None] = mapped_column(Text, nullable=True)
