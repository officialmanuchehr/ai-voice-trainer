import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    client_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    difficulty: Mapped[str] = mapped_column(String, nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_id: Mapped[str] = mapped_column(String, nullable=False)

    product: Mapped["Product"] = relationship(back_populates="scenarios")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"), nullable=False)
    kb_version: Mapped[str] = mapped_column(String, nullable=False)
    rubric_id: Mapped[str] = mapped_column(String, nullable=False)
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


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), nullable=False, unique=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    strengths: Mapped[list] = mapped_column(JSON, nullable=False)
    growth_areas: Mapped[list] = mapped_column(JSON, nullable=False)
    better_examples: Mapped[list] = mapped_column(JSON, nullable=False)
