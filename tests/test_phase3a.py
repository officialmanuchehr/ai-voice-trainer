"""Phase 3A — external AI service failures: safe errors, transcript
consistency, retry without duplicates, graceful degradation.

Every injected provider failure carries a distinctive marker (and a fake
credential); none of it may reach any client-facing response.
"""

from pathlib import Path

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    archive_published_scenarios,
    login,
    new_team_with_users,
    ok,
    server,
    start_session,
)

import app.main as main
from app.config import settings

SCENARIO = "scn_merchant_onboarding_medium_01"
MARKER = "SECRET_PROVIDER_ERROR_123"
RAW_ERROR = f"{MARKER}: upstream 500, body={{'error': 'boom'}}, Authorization: Bearer sk-SECRET-KEY-456"
AUDIO_MARKER = b"AUDIO_SENTINEL_BYTES_789"
AUDIO = ("turn.webm", b"\x1a\x45\xdf\xa3" + AUDIO_MARKER, "audio/webm")


def boom(*args, **kwargs):
    raise RuntimeError(RAW_ERROR)


async def aboom(*args, **kwargs):
    boom()


@pytest.fixture(scope="module")
def people(server):
    return new_team_with_users({"manager": "manager", "lead": "sales_lead"})


@pytest.fixture
def manager(people):
    return login(people["manager"])


def turns(client, session_id):
    return ok(client.get(f"/sessions/{session_id}/transcript"))["turns"]


def assert_safe(response, code, status=502):
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    assert body["detail"] == main.SERVICE_MESSAGES[code]
    assert_no_leak(response.text)


def assert_no_leak(text):
    for secret in (MARKER, "sk-SECRET-KEY-456", "Authorization", "Traceback", "RuntimeError"):
        assert secret not in text, f"leaked {secret!r}"


def sweep(people, session_id):
    """Every client-facing view of the session, for owner, lead and admin."""
    for username in (people["manager"], people["lead"], "admin"):
        client = login(username)
        for path in (f"/sessions/{session_id}/transcript", f"/sessions/{session_id}/score"):
            assert_no_leak(client.get(path).text)
    assert_no_leak(login(people["manager"]).get("/me/sessions").text)
    admin = login("admin")
    assert_no_leak(admin.get("/admin/audit").text)
    assert_no_leak(admin.get("/dashboard/data").text)


# ------------------------------------------------------------ text turn


def test_text_turn_dialog_failure_stores_nothing_and_retry_adds_one_pair(people, manager, monkeypatch):
    session_id = start_session(manager, SCENARIO)["id"]
    ok(manager.post(f"/sessions/{session_id}/turns", json={"text": "Первая реплика"}))
    before = turns(manager, session_id)

    monkeypatch.setattr(main.dialog_provider, "respond", aboom)
    failed = manager.post(f"/sessions/{session_id}/turns", json={"text": "Реплика при сбое"})
    assert_safe(failed, "dialog_unavailable")
    assert turns(manager, session_id) == before  # neither manager nor client turn stored
    sweep(people, session_id)

    monkeypatch.undo()
    retried = ok(manager.post(f"/sessions/{session_id}/turns", json={"text": "Реплика при сбое"}))
    after = turns(manager, session_id)
    assert len(after) == len(before) + 2
    assert [t["turn_index"] for t in after] == list(range(1, len(after) + 1))
    assert (retried["manager_turn_index"], retried["ai_client_turn_index"]) == (len(before) + 1, len(before) + 2)
    assert [t["text"] for t in after[-2:]][0] == "Реплика при сбое"


def test_dialog_failure_keeps_session_active(manager, monkeypatch):
    session_id = start_session(manager, SCENARIO)["id"]
    monkeypatch.setattr(main.dialog_provider, "respond", aboom)
    assert_safe(manager.post(f"/sessions/{session_id}/turns", json={"text": "x"}), "dialog_unavailable")
    assert ok(manager.get(f"/sessions/{session_id}/transcript"))["status"] == "active"
    # No turns stored, so the session can't be finished yet (unchanged rule).
    assert manager.post(f"/sessions/{session_id}/finish").status_code == 400


# ------------------------------------------------------------ voice turn


def _db_bytes():
    return Path(settings.database_url.split("///", 1)[1]).read_bytes()


def test_stt_failure_stores_nothing_and_skips_the_ai_client(people, manager, monkeypatch):
    session_id = start_session(manager, SCENARIO)["id"]
    before = turns(manager, session_id)
    dialog_calls = []

    async def spy(system_prompt, messages):
        dialog_calls.append(1)
        return "ответ"

    monkeypatch.setattr(main.stt_provider, "transcribe", aboom)
    monkeypatch.setattr(main.dialog_provider, "respond", spy)
    failed = manager.post(f"/sessions/{session_id}/voice-turn", files={"audio": AUDIO})
    assert_safe(failed, "stt_unavailable")
    assert "manager_text" not in failed.json()
    assert dialog_calls == []
    assert turns(manager, session_id) == before
    assert AUDIO_MARKER not in _db_bytes()  # audio never persisted
    sweep(people, session_id)


def test_dialog_failure_after_stt_returns_recognised_text_for_resend(people, manager, monkeypatch):
    session_id = start_session(manager, SCENARIO)["id"]
    before = turns(manager, session_id)

    async def recognised(audio, lang, vocab):
        return "Распознанная реплика менеджера"

    monkeypatch.setattr(main.stt_provider, "transcribe", recognised)
    monkeypatch.setattr(main.dialog_provider, "respond", aboom)
    failed = manager.post(f"/sessions/{session_id}/voice-turn", files={"audio": AUDIO})
    assert_safe(failed, "dialog_unavailable")
    assert failed.json()["manager_text"] == "Распознанная реплика менеджера"
    assert turns(manager, session_id) == before  # no partial pair
    assert AUDIO_MARKER not in _db_bytes()
    sweep(people, session_id)

    # Resend the recognised text (no re-recording): exactly one pair.
    monkeypatch.undo()
    ok(manager.post(f"/sessions/{session_id}/turns", json={"text": failed.json()["manager_text"]}))
    after = turns(manager, session_id)
    assert len(after) == len(before) + 2
    assert after[-2]["text"] == "Распознанная реплика менеджера" and after[-2]["role"] == "manager"


def test_empty_recognition_unchanged(manager, monkeypatch):
    async def silence(audio, lang, vocab):
        return "   "

    session_id = start_session(manager, SCENARIO)["id"]
    monkeypatch.setattr(main.stt_provider, "transcribe", silence)
    response = manager.post(f"/sessions/{session_id}/voice-turn", files={"audio": AUDIO})
    assert response.status_code == 400
    assert turns(manager, session_id) == []


# ------------------------------------------------------------ TTS


def test_tts_failure_keeps_the_committed_turn_and_continues_in_text(people, manager, monkeypatch):
    session_id = start_session(manager, SCENARIO)["id"]
    monkeypatch.setattr(main.tts_provider, "synthesize", aboom)

    voice = manager.post(f"/sessions/{session_id}/voice-turn", files={"audio": AUDIO})
    assert voice.status_code == 200, voice.text
    body = voice.json()
    assert body["audio_error"] == "audio_unavailable"
    assert body["ai_client_audio_base64"] is None
    assert body["ai_client_text"] and body["manager_text"]
    assert_no_leak(voice.text)
    stored = turns(manager, session_id)
    assert [t["role"] for t in stored] == ["manager", "ai_client"]
    assert stored[1]["text"] == body["ai_client_text"]

    # Replaying the audio while TTS is down: safe error, transcript untouched.
    assert_safe(manager.get(f"/sessions/{session_id}/turns/2/audio"), "audio_unavailable")
    assert turns(manager, session_id) == stored

    # The conversation continues in text.
    ok(manager.post(f"/sessions/{session_id}/turns", json={"text": "Продолжим текстом"}))
    assert len(turns(manager, session_id)) == 4
    sweep(people, session_id)

    # Once TTS is back, the stored reply can be voiced — still no new turns.
    monkeypatch.undo()
    assert manager.get(f"/sessions/{session_id}/turns/2/audio").status_code == 200
    assert len(turns(manager, session_id)) == 4


def test_successful_voice_turn_unchanged(manager):
    session_id = start_session(manager, SCENARIO)["id"]
    body = ok(manager.post(f"/sessions/{session_id}/voice-turn", files={"audio": AUDIO}))
    assert "audio_error" not in body
    assert body["ai_client_audio_base64"] == ""  # stub TTS returns empty audio
    assert len(turns(manager, session_id)) == 2


# ------------------------------------------------------------ scoring


@pytest.mark.parametrize("failing", ["verify_claims", "score"])
def test_scoring_failure_is_safe_and_retryable(people, manager, monkeypatch, failing):
    session = start_session(manager, SCENARIO)
    session_id = session["id"]
    ok(manager.post(f"/sessions/{session_id}/turns", json={"text": "Добрый день"}))
    before = turns(manager, session_id)

    monkeypatch.setattr(main.scoring_provider, failing, aboom)
    ok(manager.post(f"/sessions/{session_id}/finish"))
    assert ok(manager.post(f"/sessions/{session_id}/score-run"))["status"] == "finish_error"

    result = ok(manager.get(f"/sessions/{session_id}/score"))
    assert result == {
        "session_id": session_id,
        "status": "finish_error",
        "code": "scoring_unavailable",
        "detail": main.SERVICE_MESSAGES["scoring_unavailable"],
    }  # no total, breakdown or feedback presented
    assert turns(manager, session_id) == before
    sweep(people, session_id)

    monkeypatch.undo()
    ok(manager.post(f"/sessions/{session_id}/finish"))
    assert ok(manager.post(f"/sessions/{session_id}/score-run"))["status"] == "finished"
    final = ok(manager.get(f"/sessions/{session_id}/score"))
    assert (final["scenario_version"], final["kb_version"]) == (session["scenario_version"], session["kb_version"])
    assert isinstance(final["total"], int)
    assert turns(manager, session_id) == before


def test_scoring_timeout_message_is_also_safe(manager, monkeypatch):
    import asyncio

    async def slow(*args, **kwargs):
        await asyncio.sleep(5)

    session_id = start_session(manager, SCENARIO)["id"]
    ok(manager.post(f"/sessions/{session_id}/turns", json={"text": "Добрый день"}))
    monkeypatch.setattr(main, "_SCORING_BUDGET_SECONDS", 0.2)
    monkeypatch.setattr(main.scoring_provider, "verify_claims", slow)
    ok(manager.post(f"/sessions/{session_id}/finish"))
    assert ok(manager.post(f"/sessions/{session_id}/score-run"))["status"] == "finish_error"
    assert ok(manager.get(f"/sessions/{session_id}/score"))["code"] == "scoring_unavailable"


# ------------------------------------------------------------ frontend


def test_frontend_never_renders_raw_http_status(server):
    """The shared api() helper maps failures to safe messages and exposes the
    stable code; the training page recovers unsent text from the transcript."""
    app_js = server.get("/static/app.js").text
    assert "HTTP ${res.status}" not in app_js
    assert "code: data && data.code" in app_js
    # Phase 4A moved the training page's script out of the HTML (strict CSP).
    assert '<script src="/static/js/pages/training.js"></script>' in server.get("/").text
    training = server.get("/static/js/pages/training.js").text
    assert "async function syncChat()" in training and "manager_text" in training and "audio_error" in training
