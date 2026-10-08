"""Phase 9 — pilot acceptance tests.

A2-2 input ceilings, A2-4 persona guard, and end-to-end proofs of the
pilot's central invariants: version binding, the mis-selling cap, KB review
guards, the six-role RBAC matrix, a security smoke test and the active-
session reload behaviour. Stub providers only — no paid calls.
"""

import json

import pytest
from fastapi.testclient import TestClient
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    CRITERIA,
    approve_and_publish_scenario,
    archive_published_scenarios,
    finish_and_score,
    kb_data,
    login,
    new_product,
    new_team_with_users,
    ok,
    publish_kb,
    say,
    scenario_data,
    server,
    start_session,
    uid,
)

import app.main as main
from app import limits
from app.persona_guard import FALLBACK_REPLIES, guard_client_reply, persona_break

SEED = "scn_merchant_onboarding_medium_01"


def live_scenario(product_id=None, **overrides):
    """A published scenario on a fresh product with a published clean KB."""
    pid = product_id or uid("p9")
    if product_id is None:
        publish_kb(pid, "1.0.0", kb_data(pid))
    trainer = login("trainer1")
    sid = ok(trainer.post("/admin/scenarios", json={"data": scenario_data(pid, **overrides)}))["id"]
    approve_and_publish_scenario(sid, 1)
    return pid, sid


# ================================================================ A2-2 limits


def test_turn_text_boundary(server):
    client = login("manager1")
    session = start_session(client, SEED)["id"]
    assert client.post(f"/sessions/{session}/turns", json={"text": "а" * limits.MAX_TURN_CHARS}).status_code == 200
    response = client.post(f"/sessions/{session}/turns", json={"text": "а" * (limits.MAX_TURN_CHARS + 1)})
    assert response.status_code == 422 and "2000" in response.json()["detail"]
    assert len(ok(client.get(f"/sessions/{session}/transcript"))["turns"]) == 2  # nothing stored for the refused turn


def test_turns_per_session_ceiling(server, monkeypatch):
    monkeypatch.setattr(limits, "MAX_MANAGER_TURNS", 3)
    monkeypatch.setattr(main, "MAX_MANAGER_TURNS", 3)
    client = login("manager1")
    session = start_session(client, SEED)["id"]
    for _ in range(3):
        say(client, session)
    refused = client.post(f"/sessions/{session}/turns", json={"text": "ещё"})
    assert refused.status_code == 422 and "завершите" in refused.json()["detail"]
    finish_and_score(client, session)  # the session can still be finished and scored


def test_audio_size_ceiling_rejects_before_stt(server, monkeypatch):
    calls = []

    async def transcribe(audio, lang, vocab):
        calls.append(len(audio))
        return "Добрый день"

    monkeypatch.setattr(main.stt_provider, "transcribe", transcribe)
    monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 1000)
    client = login("manager1")
    session = start_session(client, SEED)["id"]
    big = client.post(f"/sessions/{session}/voice-turn", files={"audio": ("a.webm", b"x" * 1001, "audio/webm")})
    assert big.status_code == 413 and calls == []
    assert client.post(f"/sessions/{session}/voice-turn", files={"audio": ("a.webm", b"x" * 1000, "audio/webm")}).status_code == 200
    assert calls == [1000]


def test_dispute_comment_boundary(server):
    client = login("manager1")
    session = start_session(client, SEED)["id"]
    say(client, session)
    finish_and_score(client, session)
    assert client.post(f"/sessions/{session}/dispute", json={"comment": "x" * (limits.MAX_DISPUTE_CHARS + 1)}).status_code == 422
    ok(client.post(f"/sessions/{session}/dispute", json={"comment": "x" * limits.MAX_DISPUTE_CHARS}))
    assert len(ok(client.get(f"/sessions/{session}/score"))["dispute"]["comment"]) == limits.MAX_DISPUTE_CHARS


def test_login_field_ceilings(server):
    anonymous = TestClient(main.app)
    assert anonymous.post("/auth/login", json={"username": "u" * 101, "password": "x"}).status_code == 422
    assert anonymous.post("/auth/login", json={"username": "admin", "password": "p" * 257}).status_code == 422
    assert anonymous.post("/auth/login", json={"username": "admin", "password": "demo12345"}).status_code == 200


def test_admin_field_ceilings(server):
    admin = login("admin")
    base = {"role": "manager", "password": "12345678", "team_id": None}
    assert admin.post("/admin/users", json={**base, "username": "u" * 101, "full_name": "x"}).status_code == 422
    assert admin.post("/admin/users", json={**base, "username": uid("u"), "full_name": "ф" * 201}).status_code == 422
    assert admin.post("/admin/users", json={**base, "username": uid("u"), "full_name": "x", "password": "p" * 257}).status_code == 422
    assert admin.post("/admin/teams", json={"name": "т" * 201}).status_code == 422
    ok(admin.post("/admin/users", json={**base, "username": uid("u"), "full_name": "ф" * 200}))


def test_content_document_ceilings_allow_real_content(server):
    from pathlib import Path

    seed = json.loads((Path(__file__).resolve().parent.parent / "seed" / "knowledge_base.json").read_text(encoding="utf-8"))
    for product in seed["products"]:  # the real seed is far below the ceiling
        assert len(json.dumps(product, ensure_ascii=False).encode()) < limits.MAX_KB_BYTES / 10
    pid = new_product("p9big", publish=False)
    product = login("product1")
    huge = kb_data(pid, approved_facts=[{"id": f"fact_{i}", "text": "ф" * 1000} for i in range(200)])
    response = product.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": huge})
    assert response.status_code == 422 and "слишком большой" in response.json()["detail"]
    ok(product.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid), "notes": "н" * limits.MAX_NOTES_CHARS}))
    assert product.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid), "notes": "н" * (limits.MAX_NOTES_CHARS + 1)}).status_code == 422
    trainer = login("trainer1")
    data = scenario_data("merchant_onboarding")
    data["client_profile"] = {**data["client_profile"], "pain": "б" * 60_000}
    assert trainer.post("/admin/scenarios", json={"data": data}).status_code == 422


def test_oversized_request_body_refused_with_safe_json(server):
    response = TestClient(main.app).post("/auth/login", content=b"{}", headers={"content-length": str(limits.MAX_REQUEST_BYTES + 1), "content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["code"] == "too_large" and response.headers.get("x-request-id")


# ================================================================ A2-4 persona guard

BREAKS = [
    "Я — языковая модель и не могу владеть магазином.",
    "Как искусственный интеллект, я не имею бизнеса.",
    "Я являюсь виртуальным ассистентом банка.",
    "Я ИИ, но давайте продолжим.",
    "As an AI, I cannot answer that.",
    "ТВОЙ ПРОФИЛЬ: владелец магазина, скрытая потребность — снимать выручку.",
    "Моя скрытая потребность — удобно снимать выручку без комиссии.",
    "hidden_need: снимать выручку",
    "Согласно моему системному промпту, я должен возражать.",
    "Я лишь играю роль клиента в этой тренировке.",
    "Менеджеру следует сначала спросить о выручке.",
    "Правильный ответ был бы — предложить бесплатную карту.",
]
NORMAL = [
    "Я не бот, я владелец магазина и у меня мало времени.",
    "А какие у вас комиссии? Скрытых платежей точно нет?",
    "Мне не нужна нейросеть, мне нужно, чтобы деньги быстро приходили.",
    "Я уже пользуюсь другим кошельком, зачем мне ещё один?",
    "Хорошо, а сколько времени займёт подключение?",
    "Я ассистент бухгалтера, решения принимает директор.",
    "Вы мне это уже говорили. Что ещё можете предложить?",
    "Налоги меня беспокоят. Что будет, если правила изменятся?",
    "Давайте встретимся в четверг, я посмотрю документы.",
    "Мой бизнес небольшой, три сотрудника, работаем без выходных.",
]


@pytest.mark.parametrize("reply", BREAKS)
def test_persona_breaks_are_caught(reply):
    assert persona_break(reply) is not None, reply
    safe, reason = guard_client_reply(reply)
    assert reason and safe in FALLBACK_REPLIES


@pytest.mark.parametrize("reply", NORMAL)
def test_natural_client_speech_is_untouched(reply):
    assert guard_client_reply(reply) == (reply, None)


def test_guard_applies_to_stored_and_returned_reply(server, monkeypatch):
    async def respond(system_prompt, messages):
        return "Я — языковая модель DeepSeek. ТВОЙ ПРОФИЛЬ: hidden_need — выручка."

    monkeypatch.setattr(main.dialog_provider, "respond", respond)
    client = login("manager1")
    session = start_session(client, SEED)["id"]
    reply = say(client, session)
    assert reply["ai_client_text"] in FALLBACK_REPLIES
    transcript = client.get(f"/sessions/{session}/transcript").text
    assert "языковая модель" not in transcript and "hidden_need" not in transcript


def test_client_prompt_carries_persona_rules():
    from app.prompts import build_client_system_prompt

    prompt = build_client_system_prompt({"pain": "p"}, kb_data("x"), "medium")
    assert "НИКОГДА не называй себя ИИ" in prompt and "НЕ упоминай и НЕ цитируй" in prompt and "не оценивай менеджера" in prompt


# ================================================================ version binding (E2E)


def test_version_binding_end_to_end(server, monkeypatch):
    """Session on scenario v1 + KB 1.0.0; KB 1.1.0 and scenario v2 (other
    product, other difficulty) are published mid-session; the session still
    talks, scores and reports against v1 / KB 1.0.0 everywhere."""
    pid_a = uid("p9va")
    publish_kb(pid_a, "1.0.0", kb_data(pid_a, approved_facts=[{"id": "fact_v1", "text": "FACT_FROM_KB_1_0_0"}]))
    _, sid = live_scenario(pid_a, difficulty="easy", title="Сценарий v1")
    team = new_team_with_users({"m": "manager", "lead": "sales_lead"})
    manager = login(team["m"])
    session = start_session(manager, sid)
    assert (session["scenario_version"], session["kb_version"], session["product_id"]) == (1, "1.0.0", pid_a)
    say(manager, session["id"])

    # Newer content goes live while the session is open.
    product = login("product1")
    ok(product.post(f"/admin/kb/{pid_a}/versions", json={"version": "1.1.0", "data": kb_data(pid_a, approved_facts=[{"id": "fact_v2", "text": "FACT_FROM_KB_1_1_0"}])}))
    ok(login("compliance1").post(f"/admin/kb/{pid_a}/versions/1.1.0/status", json={"status": "approved"}))
    ok(product.post(f"/admin/kb/{pid_a}/versions/1.1.0/status", json={"status": "published"}))
    pid_b = uid("p9vb")
    publish_kb(pid_b, "1.0.0", kb_data(pid_b))
    ok(login("trainer1").put(f"/admin/scenarios/{sid}", json={"data": scenario_data(pid_b, difficulty="hard", title="Сценарий v2")}))
    approve_and_publish_scenario(sid, 2)

    prompts, claim_kbs = [], []
    original_respond, original_verify = main.dialog_provider.respond, main.scoring_provider.verify_claims

    async def respond(system_prompt, messages):
        prompts.append(system_prompt)
        return await original_respond(system_prompt, messages)

    async def verify_claims(transcript, kb):
        claim_kbs.append(json.dumps(kb, ensure_ascii=False))
        return await original_verify(transcript, kb)

    monkeypatch.setattr(main.dialog_provider, "respond", respond)
    monkeypatch.setattr(main.scoring_provider, "verify_claims", verify_claims)
    say(manager, session["id"], "Ещё вопрос")
    assert "FACT_FROM_KB_1_0_0" in prompts[-1] and "FACT_FROM_KB_1_1_0" not in prompts[-1]
    finish_and_score(manager, session["id"])
    assert "FACT_FROM_KB_1_0_0" in claim_kbs[-1] and "FACT_FROM_KB_1_1_0" not in claim_kbs[-1]

    row = next(r for r in ok(manager.get("/me/sessions")) if r["id"] == session["id"])
    assert (row["scenario_version"], row["kb_version"], row["product_id"], row["difficulty"], row["title"]) == (1, "1.0.0", pid_a, "easy", "Сценарий v1")
    progress = ok(manager.get("/me/progress"))
    assert [p["product_id"] for p in progress["products"]] == [pid_a]
    lead = login(team["lead"])
    manager_id = ok(manager.get("/auth/me"))["id"]
    drill = ok(lead.get(f"/dashboard/managers/{manager_id}/progress"))
    assert [p["product_id"] for p in drill["products"]] == [pid_a]
    assert {p["product_id"] for p in ok(lead.get("/dashboard/data?days=0"))["products"]} == {pid_a}
    # A new session binds to the new versions.
    new = start_session(manager, sid)
    assert (new["scenario_version"], new["kb_version"], new["product_id"]) == (2, "1.0.0", pid_b)


# ================================================================ mis-selling (E2E)


@pytest.mark.parametrize("verdict", ["unapproved", "forbidden", "maybe-approved"])
def test_mis_selling_claim_caps_the_stored_score_everywhere(server, monkeypatch, verdict):
    async def verify_claims(transcript, kb):
        return [{"claim_text": "Кредит одобрим без залога", "turn_index": 1, "verdict": verdict, "matched_entry_id": None, "reason": "нет в БЗ"}]

    async def score(transcript, rubric, claim_checks):  # an over-generous evaluator that omits the critical error
        return {"breakdown": [{"criterion_id": c, "score": 95, "max": 100} for c in CRITERIA], "critical_errors": [],
                "feedback": {"summary": "s", "strengths": [], "growth_areas": [], "better_examples": [], "next_skill": None}}

    monkeypatch.setattr(main.scoring_provider, "verify_claims", verify_claims)
    monkeypatch.setattr(main.scoring_provider, "score", score)
    team = new_team_with_users({"m": "manager", "lead": "sales_lead"})
    manager = login(team["m"])
    session = start_session(manager, SEED)["id"]
    say(manager, session, "Кредит одобрим без залога, гарантирую")
    result = finish_and_score(manager, session)
    assert result["total"] == 60
    assert result["cap_reason"] and any(t["kind"] == "claim" for t in result["cap_reason"]["triggers"])
    stored_verdicts = {c["verdict"] for c in result["claim_checks"]}
    assert stored_verdicts <= {"unapproved", "forbidden"}  # an unknown verdict failed closed
    assert next(r for r in ok(manager.get("/me/sessions")) if r["id"] == session)["total"] == 60
    assert ok(manager.get("/me/progress"))["summary"]["latest_score"] == 60
    assert ok(login(team["lead"]).get("/dashboard/data?days=0"))["kpi"]["avg_score"] == 60


# ================================================================ KB safety (E2E)


def test_kb_safety_chain(server):
    pid = uid("p9k")
    product, compliance, trainer = login("product1"), login("compliance1"), login("trainer1")
    flagged = kb_data(pid, approved_facts=[{"id": "fact_1", "text": "Синтетический факт", "needs_review": True}])
    ok(product.post(f"/admin/kb/{pid}/versions", json={"version": "1.0.0", "data": flagged}))
    # unreviewed KB → cannot approve or publish
    assert compliance.post(f"/admin/kb/{pid}/versions/1.0.0/status", json={"status": "approved"}).json()["code"] == "kb_unreviewed"
    # a scenario for a product without a published KB → cannot publish
    sid = ok(trainer.post("/admin/scenarios", json={"data": scenario_data(pid)}))["id"]
    ok(product.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}))
    assert trainer.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}).status_code == 409
    # explicit review → approve → publish → scenario follows the lifecycle
    ok(product.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid)}))
    ok(compliance.post(f"/admin/kb/{pid}/versions/1.0.0/status", json={"status": "approved"}))
    ok(product.post(f"/admin/kb/{pid}/versions/1.0.0/status", json={"status": "published"}))
    ok(trainer.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "published"}))
    session = start_session(login("manager1"), sid)
    assert session["kb_version"] == "1.0.0"
    # a later KB publication does not rewrite that session
    ok(product.post(f"/admin/kb/{pid}/versions", json={"version": "2.0.0", "base_version": "1.0.0"}))
    ok(compliance.post(f"/admin/kb/{pid}/versions/2.0.0/status", json={"status": "approved"}))
    ok(product.post(f"/admin/kb/{pid}/versions/2.0.0/status", json={"status": "published"}))
    assert next(r for r in ok(login("manager1").get("/me/sessions")) if r["id"] == session["id"])["kb_version"] == "1.0.0"


# ================================================================ RBAC matrix (six roles)

ROLES = ["manager", "lead", "training", "product", "compliance", "admin"]


@pytest.fixture(scope="module")
def world(server):
    a = new_team_with_users({"manager": "manager", "lead": "sales_lead"})
    b = new_team_with_users({"manager": "manager"})
    users = {"manager": a["manager"], "lead": a["lead"], "training": "trainer1", "product": "product1", "compliance": "compliance1", "admin": "admin"}
    sessions = {}
    for key, username in (("own", a["manager"]), ("cross", b["manager"])):
        client = login(username)
        sid = start_session(client, SEED)["id"]
        say(client, sid)
        finish_and_score(client, sid)
        sessions[key] = sid
    ids = {"a": ok(login(a["manager"]).get("/auth/me"))["id"], "b": ok(login(b["manager"]).get("/auth/me"))["id"]}
    return {"users": users, "s": sessions, "ids": ids}


# expected status per role, in ROLES order
MATRIX = [
    ("team-A manager's score", "/sessions/{own}/score", [200, 200, 403, 403, 403, 200]),
    ("team-A manager's transcript", "/sessions/{own}/transcript", [200, 200, 403, 403, 403, 200]),
    ("team-B manager's score", "/sessions/{cross}/score", [403, 403, 403, 403, 403, 200]),
    ("team-B manager's transcript", "/sessions/{cross}/transcript", [403, 403, 403, 403, 403, 200]),
    ("team-A manager analytics", "/dashboard/managers/{a}/progress", [403, 200, 403, 403, 403, 200]),
    ("team-A manager history", "/dashboard/managers/{a}/sessions", [403, 200, 403, 403, 403, 200]),
    ("team-B manager analytics", "/dashboard/managers/{b}/progress", [403, 403, 403, 403, 403, 200]),
    ("team / org analytics", "/dashboard/data?days=0", [403, 200, 200, 200, 200, 200]),
    ("own progress", "/me/progress", [200, 200, 200, 403, 403, 200]),
    # Any signed-in user may list their OWN sessions (none for roles that cannot train).
    ("own history", "/me/sessions", [200, 200, 200, 200, 200, 200]),
    ("training catalogue", "/scenarios", [200, 200, 200, 403, 403, 200]),
    ("scenario admin", "/admin/scenarios", [403, 403, 200, 200, 200, 200]),
    ("knowledge base admin", "/admin/kb", [403, 403, 200, 200, 200, 200]),
    ("work queue", "/admin/queue", [403, 403, 200, 200, 200, 200]),
    ("audit log", "/admin/audit?limit=5", [403, 403, 403, 403, 200, 200]),
    ("users", "/admin/users", [403, 403, 403, 403, 403, 200]),
    ("teams", "/admin/teams", [403, 403, 403, 403, 403, 200]),
]


@pytest.mark.parametrize("label,path,expected", MATRIX, ids=[m[0] for m in MATRIX])
def test_rbac_read_matrix(world, label, path, expected):
    url = path.format(own=world["s"]["own"], cross=world["s"]["cross"], a=world["ids"]["a"], b=world["ids"]["b"])
    got = [login(world["users"][role]).get(url).status_code for role in ROLES]
    assert got == expected, dict(zip(ROLES, got))


def test_own_history_is_own_data_only(world):
    for role in ("product", "compliance"):
        assert ok(login(world["users"][role]).get("/me/sessions")) == []
    own = {r["id"] for r in ok(login(world["users"]["lead"]).get("/me/sessions"))}
    assert world["s"]["own"] not in own and world["s"]["cross"] not in own


def test_rbac_dispute_only_owner(world):
    url = f"/sessions/{world['s']['own']}/dispute"
    got = {role: login(world["users"][role]).post(url, json={"comment": "x"}).status_code for role in ROLES if role != "manager"}
    assert set(got.values()) == {403}, got
    assert login(world["users"]["manager"]).post(url, json={"comment": "x"}).status_code == 200


@pytest.mark.parametrize("role,scenario_approve,kb_approve,kb_edit,start_session_status", [
    ("manager", 403, 403, 403, 200), ("lead", 403, 403, 403, 200), ("training", 403, 403, 403, 200),
    ("product", 200, 403, 200, 403), ("compliance", 200, 200, 200, 403), ("admin", 200, 200, 200, 200),
])
def test_rbac_write_matrix(world, role, scenario_approve, kb_approve, kb_edit, start_session_status):
    client = login(world["users"][role])
    sid = ok(login("trainer1").post("/admin/scenarios", json={"data": scenario_data("merchant_onboarding")}))["id"]
    assert client.post(f"/admin/scenarios/{sid}/versions/1/status", json={"status": "approved"}).status_code == scenario_approve
    pid = new_product("p9r", publish=False)
    assert client.put(f"/admin/kb/{pid}/versions/1.0.0", json={"data": kb_data(pid)}).status_code == kb_edit
    assert client.post(f"/admin/kb/{pid}/versions/1.0.0/status", json={"status": "approved"}).status_code == kb_approve
    assert client.post("/sessions", json={"scenario_id": SEED}).status_code == start_session_status


# ================================================================ security smoke


def test_security_headers_and_cookie_flags(server):
    anonymous = TestClient(main.app)
    for path in ("/login", "/health"):
        headers = anonymous.get(path).headers
        assert "default-src 'self'" in headers["content-security-policy"] and "unsafe-inline" not in headers["content-security-policy"]
        assert headers["x-frame-options"] == "DENY" and headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "same-origin" and "microphone=(self)" in headers["permissions-policy"]
        assert len(headers["x-request-id"]) == 32
    https = anonymous.post("/auth/login", json={"username": "admin", "password": "demo12345"}, headers={"x-forwarded-proto": "https"})
    cookie = https.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" in cookie


def test_malformed_requests_get_safe_errors(server):
    client = login("manager1")
    bad_json = client.post("/sessions", content=b"{not json", headers={"content-type": "application/json"})
    assert bad_json.status_code == 422 and "Traceback" not in bad_json.text
    assert client.post("/sessions", json={"scenario_id": ["x"]}).status_code == 422
    assert client.get("/sessions/does-not-exist/score").status_code == 404
    assert client.get("/sessions/../admin/users").status_code in (403, 404)
    assert TestClient(main.app).get("/me/progress").status_code == 401


def test_stub_providers_on_postgres_are_flagged(monkeypatch):
    monkeypatch.setattr(main.settings, "database_url", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setattr(main.settings, "scoring_provider", "stub")
    monkeypatch.setattr(main.settings, "dialog_provider", "deepseek")
    assert "SCORING_PROVIDER" in main.stub_providers_in_production() and "DIALOG_PROVIDER" not in main.stub_providers_in_production()
    monkeypatch.setattr(main.settings, "database_url", "sqlite+aiosqlite:///x.db")
    assert main.stub_providers_in_production() == []


# ================================================================ active-session reload


def test_reload_mid_session_loses_nothing_and_corrupts_nothing(server):
    """A reload abandons the open session: it stays stored as active with its
    committed turns; a new session is independent; nothing is duplicated."""
    client = login("manager1")
    first = start_session(client, SEED)["id"]
    say(client, first, "Первая реплика")
    before = ok(client.get(f"/sessions/{first}/transcript"))["turns"]
    # "reload": the page forgets the session id and the manager starts again
    second = start_session(client, SEED)["id"]
    say(client, second, "Новая тренировка")
    finish_and_score(client, second)
    after = ok(client.get(f"/sessions/{first}/transcript"))["turns"]
    assert after == before and [t["turn_index"] for t in after] == [1, 2]
    rows = {r["id"]: r for r in ok(client.get("/me/sessions"))}
    assert rows[first]["status"] == "active" and rows[second]["status"] == "finished"
    # the abandoned session can still be finished and scored later
    finish_and_score(client, first)
