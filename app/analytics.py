"""Dashboard aggregates (PRD §11). Computed in Python over the period's rows —
fine at pilot scale (hundreds of sessions); move to SQL aggregates if it grows.

Results are informational only: nothing here feeds a manager's KPI (PRD §11).
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClaimCheck, Feedback, Product, Scenario, ScenarioVersion, Score, TranscriptTurn, User
from app.models import Session as SessionModel
from app.seed_loader import list_rubrics

NEEDS_HELP_SCORE = 60
NEEDS_HELP_CRITICAL_RATE = 0.3


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes even for timezone=True columns.
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def criterion_names() -> dict[str, str]:
    return {c["id"]: c["name"] for r in list_rubrics() for c in r["criteria"]}


async def _scenario_versions(db: AsyncSession) -> dict[tuple[str, int], dict]:
    rows = (await db.execute(select(ScenarioVersion.scenario_id, ScenarioVersion.version, ScenarioVersion.data))).all()
    return {(sid, v): data or {} for sid, v, data in rows}


def bound_scenario(session: SessionModel, versions: dict[tuple[str, int], dict], scenarios: dict[str, Scenario]) -> dict:
    """Title, product and difficulty of the scenario version the session was
    bound to — never the scenario's current version, so publishing a new
    version can't reclassify history. The current scenario row is only a
    fallback for a session whose version record doesn't exist."""
    data = versions.get((session.scenario_id, session.scenario_version or 1))
    if data:
        return {"title": data.get("title") or session.scenario_id, "product_id": data.get("product_id"), "difficulty": data.get("difficulty")}
    scenario = scenarios.get(session.scenario_id)
    return {
        "title": (scenario.title if scenario else None) or session.scenario_id,
        "product_id": scenario.product_id if scenario else None,
        "difficulty": scenario.difficulty if scenario else None,
    }


async def session_rows(db: AsyncSession, user_ids: list[str]) -> list[dict]:
    """Session history for the given users, newest first (manager's own history
    and a lead's drill-down into one manager)."""
    sessions = (
        await db.execute(
            select(SessionModel).where(SessionModel.user_id.in_(user_ids)).order_by(SessionModel.started_at.desc())
        )
    ).scalars().all()
    ids = [s.id for s in sessions]
    scores = {sc.session_id: sc for sc in (await db.execute(select(Score).where(Score.session_id.in_(ids)))).scalars()}
    scenarios = {s.id: s for s in (await db.execute(select(Scenario))).scalars()}
    products = {p.id: p.name for p in (await db.execute(select(Product))).scalars()}
    versions = await _scenario_versions(db)
    rows = []
    for s in sessions:
        scenario = scenarios.get(s.scenario_id)
        bound = bound_scenario(s, versions, scenarios)
        score = scores.get(s.id)
        rows.append(
            {
                "id": s.id,
                "scenario_id": s.scenario_id,
                "scenario_version": s.scenario_version or 1,
                "title": bound["title"],
                "product_id": bound["product_id"],
                "product_name": products.get(bound["product_id"]),
                "difficulty": bound["difficulty"],
                "kb_version": s.kb_version,
                "status": s.status,
                "started_at": _aware(s.started_at).isoformat(),
                "total": score.total if score else None,
                "critical_errors": len(score.critical_errors) if score else 0,
                "disputed": bool(score and score.disputed_at),
                "scenario_available": bool(scenario and scenario.published_version),
            }
        )
    return rows


async def build_dashboard(
    db: AsyncSession,
    viewer: User,
    days: int | None,
    product_id: str | None,
    team_id: int | None,
    named: bool,
) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days) if days else None

    manager_query = select(User).where(User.role == "manager", User.is_active.is_(True))
    if team_id is not None:
        manager_query = manager_query.where(User.team_id == team_id)
    managers = (await db.execute(manager_query)).scalars().all()
    all_users = {u.id: u for u in (await db.execute(select(User))).scalars()}

    session_query = select(SessionModel)
    if team_id is not None:
        session_query = session_query.where(SessionModel.user_id.in_([m.id for m in managers]))
    scenarios = {s.id: s for s in (await db.execute(select(Scenario))).scalars()}
    products = {p.id: p.name for p in (await db.execute(select(Product))).scalars()}
    versions = await _scenario_versions(db)

    sessions = []
    for s in (await db.execute(session_query)).scalars():
        started = _aware(s.started_at)
        if since and started < since:
            continue
        pid = bound_scenario(s, versions, scenarios)["product_id"]  # the session's bound version
        if product_id and pid != product_id:
            continue
        sessions.append((s, started, pid))

    ids = [s.id for s, _, _ in sessions]
    scores = {sc.session_id: sc for sc in (await db.execute(select(Score).where(Score.session_id.in_(ids)))).scalars()}
    feedback = {f.session_id: f for f in (await db.execute(select(Feedback).where(Feedback.session_id.in_(ids)))).scalars()}
    verdicts = Counter((await db.execute(select(ClaimCheck.verdict).where(ClaimCheck.session_id.in_(ids)))).scalars())
    latencies = list(
        (
            await db.execute(
                select(TranscriptTurn.latency_ms).where(
                    TranscriptTurn.session_id.in_(ids), TranscriptTurn.latency_ms.is_not(None)
                )
            )
        ).scalars()
    )

    names = criterion_names()
    scored = [(s, started, pid, scores[s.id]) for s, started, pid in sessions if s.id in scores]

    # Skills: share of the criterion's max, averaged over scored sessions.
    skill_values: dict[str, list[float]] = defaultdict(list)
    for *_, score in scored:
        for item in score.breakdown or []:
            maximum = item.get("max") or 0
            if maximum:
                skill_values[item["criterion_id"]].append(min(max(item.get("score", 0), 0), maximum) / maximum)
    skills = sorted(
        (
            {"criterion_id": cid, "name": names.get(cid, cid), "avg_pct": round(sum(v) / len(v) * 100), "samples": len(v)}
            for cid, v in skill_values.items()
        ),
        key=lambda x: x["avg_pct"],
    )

    # Weekly trend (weeks start on Monday).
    weekly: dict[str, list[int]] = defaultdict(list)
    weekly_count: Counter = Counter()
    for s, started, _, *rest in sessions:
        week = (started - timedelta(days=started.weekday())).date().isoformat()
        weekly_count[week] += 1
    for s, started, _, score in scored:
        week = (started - timedelta(days=started.weekday())).date().isoformat()
        weekly[week].append(score.total)
    trend = [
        {"week_start": w, "sessions": weekly_count[w], "avg_score": _avg(weekly.get(w, []))} for w in sorted(weekly_count)
    ]

    # Products.
    per_product: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "scores": [], "critical": 0})
    for s, _, pid, *_ in sessions:
        per_product[pid]["sessions"] += 1
    for s, _, pid, score in scored:
        per_product[pid]["scores"].append(score.total)
        per_product[pid]["critical"] += 1 if score.critical_errors else 0
    product_rows = sorted(
        (
            {
                "product_id": pid,
                "name": products.get(pid, pid),
                "sessions": d["sessions"],
                "scored": len(d["scores"]),
                "avg_score": _avg(d["scores"]),
                "critical_rate": round(d["critical"] / len(d["scores"]) * 100) if d["scores"] else None,
            }
            for pid, d in per_product.items()
        ),
        key=lambda x: (x["avg_score"] is None, x["avg_score"] or 0),
    )

    # Risks.
    error_types = Counter(e.get("type") for *_, score in scored for e in (score.critical_errors or []))
    critical_sessions = sum(1 for *_, score in scored if score.critical_errors)

    # Managers (named views only).
    manager_rows = []
    if named:
        by_user: dict[str, list] = defaultdict(list)
        for s, started, pid, score in scored:
            by_user[s.user_id].append((started, score))
        started_by_user = Counter(s.user_id for s, *_ in sessions)
        for m in managers:
            history = sorted(by_user.get(m.id, []), key=lambda x: x[0])
            totals = [sc.total for _, sc in history]
            critical_rate = sum(1 for _, sc in history if sc.critical_errors) / len(history) if history else 0
            user_skills: dict[str, list[float]] = defaultdict(list)
            for _, sc in history:
                for item in sc.breakdown or []:
                    if item.get("max"):
                        user_skills[item["criterion_id"]].append(item.get("score", 0) / item["max"])
            weakest = min(user_skills.items(), key=lambda kv: sum(kv[1]) / len(kv[1]), default=None)
            reasons = []
            if not started_by_user.get(m.id):
                reasons.append("нет тренировок за период")
            if totals and _avg(totals) < NEEDS_HELP_SCORE:
                reasons.append(f"средний балл ниже {NEEDS_HELP_SCORE}")
            if history and critical_rate >= NEEDS_HELP_CRITICAL_RATE:
                reasons.append("частые критичные ошибки")
            if len(totals) >= 2 and totals[-1] - totals[0] <= -10:
                reasons.append("балл снижается")
            manager_rows.append(
                {
                    "user_id": m.id,
                    "full_name": m.full_name or m.username,
                    "sessions": started_by_user.get(m.id, 0),
                    "scored": len(totals),
                    "avg_score": _avg(totals),
                    "first_score": totals[0] if totals else None,
                    "last_score": totals[-1] if totals else None,
                    "critical_rate": round(critical_rate * 100) if history else None,
                    "weakest_skill": names.get(weakest[0], weakest[0]) if weakest else None,
                    "last_session_at": history[-1][0].isoformat() if history else None,
                    "needs_help": bool(reasons),
                    "reasons": reasons,
                }
            )
        manager_rows.sort(key=lambda r: (not r["needs_help"], r["avg_score"] if r["avg_score"] is not None else -1))

    # Recommendations (PRD §11 «рекомендации по темам обучения»).
    recommendations = [
        f"Тренинг по навыку «{s['name']}»: в среднем {s['avg_pct']}% от максимума."
        for s in skills
        if s["avg_pct"] < 60
    ][:3]
    if error_types:
        top_type, top_count = error_types.most_common(1)[0]
        recommendations.append(f"Разобрать с командой критичную ошибку «{top_type}» — {top_count} случ.")
    scored_products = [p for p in product_rows if p["avg_score"] is not None]
    if len(scored_products) >= 2:
        weakest_product = scored_products[0]
        recommendations.append(
            f"Больше тренировок по продукту «{weakest_product['name']}» — самый низкий средний балл ({weakest_product['avg_score']})."
        )
    next_skills = Counter(f.next_skill for f in feedback.values() if f.next_skill)
    if next_skills:
        skill, count = next_skills.most_common(1)[0]
        recommendations.append(f"Оценщик чаще всего советует тренировать: «{skill}» ({count} сесс.).")

    disputes = [
        {
            "session_id": s.id,
            "full_name": (all_users[s.user_id].full_name or all_users[s.user_id].username)
            if named and s.user_id in all_users
            else None,
            "total": score.total,
            "comment": score.dispute_comment,
            "at": _aware(score.disputed_at).isoformat(),
        }
        for s, _, _, score in scored
        if score.disputed_at
    ]

    finished = len(scored)
    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "named": named,
        "kpi": {
            "sessions_started": len(sessions),
            "sessions_scored": finished,
            "completion_rate": round(finished / len(sessions) * 100) if sessions else None,
            "active_managers": len({s.user_id for s, *_ in sessions if s.user_id}),
            "total_managers": len(managers),
            "avg_score": _avg([score.total for *_, score in scored]),
            "critical_session_rate": round(critical_sessions / finished * 100) if finished else None,
            "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
            "dispute_rate": round(len(disputes) / finished * 100) if finished else None,
        },
        "trend": trend,
        "skills": skills,
        "products": product_rows,
        "risks": {
            "by_type": [{"type": t, "count": c} for t, c in error_types.most_common()],
            "claims": {v: verdicts.get(v, 0) for v in ("approved", "unapproved", "forbidden")},
        },
        "managers": manager_rows,
        "recommendations": recommendations,
        "disputes": disputes if named or viewer.role == "training" else [],
    }
