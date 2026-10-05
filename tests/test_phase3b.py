"""Phase 3B — pilot security hardening: login throttling, security headers,
API docs off in production, safe unexpected errors, request IDs, redaction of
stored/logged diagnostics.

Throttle tests use their own fresh users so demo accounts used by other
modules are never locked; settings changes go through monkeypatch.
"""

import logging
import re
from datetime import timedelta
from pathlib import Path

import pytest
from support import (  # noqa: F401  (server, archive_published_scenarios are fixtures)
    PASSWORD,
    archive_published_scenarios,
    login,
    ok,
    server,
    start_session,
    uid,
)

import app.login_guard as login_guard
import app.main as main
from app.config import settings
from app.database import SessionLocal
from app.http_security import CONTENT_SECURITY_POLICY
from app.models import Session as SessionModel
from app.redact import REDACTED, redact
from fastapi.testclient import TestClient

SCENARIO = "scn_merchant_onboarding_medium_01"
LIMIT = settings.login_max_failures
PASSWORD_SENTINEL = "PASSWORD_SENTINEL_PHASE3B_999"
SECRET = "SECRET_API_KEY_PHASE3B_123"


def new_user():
    username = uid("p3b")
    ok(login("admin").post("/admin/users", json={"username": username, "full_name": username, "role": "manager", "password": PASSWORD}))
    return username


def attempt(username, password, ip=None):
    headers = {"x-real-ip": ip} if ip else {}
    return TestClient(main.app).post("/auth/login", json={"username": username, "password": password}, headers=headers)


def fail(username, times, ip=None):
    return [attempt(username, PASSWORD_SENTINEL, ip).status_code for _ in range(times)]


def _db_bytes():
    return Path(settings.database_url.split("///", 1)[1]).read_bytes()


def _audit(action):
    return [r for r in ok(login("admin").get("/admin/audit?entity_type=user&limit=1000")) if r["action"] == action]


# ================================================================ throttling


def test_failures_below_threshold_are_plain_401s(server):
    username = new_user()
    assert fail(username, LIMIT - 1) == [401] * (LIMIT - 1)
    assert attempt(username, PASSWORD).status_code == 200  # still allowed below the limit


def test_threshold_then_throttled_even_with_the_right_password(server):
    username = new_user()
    assert fail(username, LIMIT) == [401] * LIMIT
    throttled = attempt(username, PASSWORD)
    assert throttled.status_code == 429
    body = throttled.json()
    assert body["code"] == "login_throttled" and "Слишком много" in body["detail"]
    retry_after = int(throttled.headers["Retry-After"])
    assert 0 < retry_after <= settings.login_window_minutes * 60 + 1
    assert attempt(username, PASSWORD_SENTINEL).status_code == 429


def test_successful_login_resets_the_counter(server):
    username = new_user()
    fail(username, LIMIT - 1)
    assert attempt(username, PASSWORD).status_code == 200
    assert fail(username, LIMIT - 1) == [401] * (LIMIT - 1)  # counting starts again
    assert attempt(username, PASSWORD).status_code == 200


def test_unknown_username_behaves_exactly_like_a_wrong_password(server):
    existing, missing = new_user(), uid("nobody")
    for _ in range(LIMIT):
        a, b = attempt(existing, PASSWORD_SENTINEL), attempt(missing, PASSWORD_SENTINEL)
        assert (a.status_code, a.json()) == (b.status_code, b.json()) == (401, {"detail": "неверный логин или пароль"})
    a, b = attempt(existing, PASSWORD), attempt(missing, PASSWORD)
    assert a.status_code == b.status_code == 429
    strip = lambda r: {k: v for k, v in r.json().items() if k != "request_id"}  # noqa: E731
    assert strip(a) == strip(b)


def test_unknown_username_pays_the_password_hash_cost(server, monkeypatch):
    calls = []
    real = login_guard.verify_password
    monkeypatch.setattr(login_guard, "verify_password", lambda p, h: calls.append(h) or real(p, h))
    attempt(uid("nobody"), "whatever")
    assert len(calls) == 1  # dummy PBKDF2 check, same work as a real user


def test_other_usernames_are_not_affected(server):
    victim, bystander = new_user(), new_user()
    fail(victim, LIMIT)
    assert attempt(victim, PASSWORD).status_code == 429
    assert attempt(bystander, PASSWORD).status_code == 200


def test_username_normalisation_shares_one_counter(server):
    username = new_user()
    variants = [username.upper(), f"  {username} ", username.capitalize(), username, username.upper()]
    for v in variants[:LIMIT]:
        attempt(v, PASSWORD_SENTINEL)
    assert attempt(username, PASSWORD).status_code == 429


def test_trusted_ip_header_separates_clients(server, monkeypatch):
    monkeypatch.setattr(settings, "client_ip_header", "x-real-ip")
    username = new_user()
    fail(username, LIMIT, ip="203.0.113.10")
    assert attempt(username, PASSWORD, ip="203.0.113.10").status_code == 429
    assert attempt(username, PASSWORD, ip="198.51.100.7").status_code == 200


def test_untrusted_ip_header_cannot_dodge_the_throttle(server, monkeypatch):
    monkeypatch.setattr(settings, "client_ip_header", "")  # header not trusted: peer address is used
    username = new_user()
    for i in range(LIMIT):
        attempt(username, PASSWORD_SENTINEL, ip=f"203.0.113.{i}")
    assert attempt(username, PASSWORD, ip="198.51.100.99").status_code == 429


def test_garbage_ip_header_falls_back_to_the_peer(server, monkeypatch):
    monkeypatch.setattr(settings, "client_ip_header", "x-real-ip")
    username = new_user()
    for i in range(LIMIT):
        attempt(username, PASSWORD_SENTINEL, ip=f"not-an-ip-{i}")
    assert attempt(username, PASSWORD, ip="still-not-an-ip").status_code == 429


def test_window_expiry_unlocks(server, monkeypatch):
    username = new_user()
    fail(username, LIMIT)
    assert attempt(username, PASSWORD).status_code == 429
    later = login_guard._now() + timedelta(minutes=settings.login_window_minutes, seconds=1)
    monkeypatch.setattr(login_guard, "_now", lambda: later)
    assert attempt(username, PASSWORD).status_code == 200


def test_password_and_username_typos_never_persisted_or_logged(server, caplog):
    # INFO and above: what a deployment logs. (At DEBUG, third-party DB drivers
    # log raw SQL parameters — never enable DEBUG logging in production.)
    caplog.set_level(logging.INFO)
    username = new_user()
    fail(username, 2)
    typo = "PWD_TYPED_INTO_USERNAME_SENTINEL_777"
    attempt(typo, "x")
    db = _db_bytes()
    for sentinel in (PASSWORD_SENTINEL, typo):
        assert sentinel.encode() not in db
        assert sentinel not in caplog.text
        assert sentinel not in login("admin").get("/admin/audit?limit=1000").text


def test_security_events_are_audited_without_noise(server):
    username = new_user()
    before_failed, before_throttled = len(_audit("auth.login_failed")), len(_audit("auth.login_throttled"))
    fail(username, LIMIT)
    for _ in range(3):
        attempt(username, PASSWORD)  # blocked attempts: not each audited
    failed = _audit("auth.login_failed")
    throttled = _audit("auth.login_throttled")
    assert len(failed) - before_failed == LIMIT
    assert len(throttled) - before_throttled == 1
    assert throttled[0]["details"]["username"] == username and throttled[0]["details"]["failures"] == LIMIT
    assert set(failed[0]["details"]) == {"username", "ip"}

    other = new_user()
    fail(other, 2)
    assert attempt(other, PASSWORD).status_code == 200
    success = next(r for r in _audit("auth.login") if r["actor"] == other)
    assert success["details"] == {"previous_failures": 2}

    attempt(uid("ghost"), "x")
    assert _audit("auth.login_failed")[0]["details"]["username"] is None  # unknown name not stored


# ================================================================ headers


@pytest.mark.parametrize("path", ["/login", "/", "/static/app.js", "/health", "/auth/me", "/scenarios"])
def test_security_headers_on_pages_assets_and_api(server, path):
    response = TestClient(main.app).get(path)
    headers = response.headers
    assert headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "same-origin"
    assert "microphone=(self)" in headers["Permissions-Policy"]
    assert re.fullmatch(r"[0-9a-f]{32}", headers["X-Request-ID"])


def test_csp_fits_the_existing_frontend(server):
    """Every page loads only same-origin resources; inline scripts/styles and
    data: audio (what the pages use) are allowed; framing is not."""
    for page in ("/login", "/", "/dashboard", "/admin", "/session"):
        html = TestClient(main.app).get(page).text
        assert not re.search(r"(src|href)=\"https?://", html), page
    for directive in ("script-src 'self' 'unsafe-inline'", "media-src 'self' data:", "connect-src 'self'", "frame-ancestors 'none'"):
        assert directive in CONTENT_SECURITY_POLICY


def test_basic_auth_rejections_also_carry_headers(server, monkeypatch):
    monkeypatch.setattr(settings, "basic_auth_username", "gate")
    monkeypatch.setattr(settings, "basic_auth_password", "gate-password")
    response = TestClient(main.app).get("/login")
    assert response.status_code == 401
    assert response.headers["X-Frame-Options"] == "DENY" and "X-Request-ID" in response.headers


def test_request_ids_are_server_generated_and_unique(server):
    client = TestClient(main.app)
    ids = {client.get("/health", headers={"X-Request-ID": "attacker-chosen"}).headers["X-Request-ID"] for _ in range(5)}
    assert len(ids) == 5 and "attacker-chosen" not in ids


# ================================================================ API docs


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_available_in_local_development(server, path):
    assert settings.api_docs_enabled  # temporary SQLite = local development
    assert TestClient(main.app).get(path).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_hidden_in_production(server, monkeypatch, path):
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://user:pw@db.example/app")
    assert not settings.api_docs_enabled  # production default, no env needed
    response = TestClient(main.app).get(path)
    assert response.status_code == 404 and "openapi" not in response.text.lower()
    monkeypatch.setattr(settings, "api_docs", True)  # explicit opt-in still possible
    assert TestClient(main.app).get(path).status_code == 200


# ================================================================ unexpected errors


def _install_crashing_route(path, message):
    if not any(getattr(r, "path", None) == path for r in main.app.routes):
        async def crash():
            raise RuntimeError(message)

        main.app.add_api_route(path, crash, methods=["GET"])


def test_unexpected_error_is_generic_with_request_id(server, caplog):
    message = f"{SECRET} SELECT * FROM users WHERE password='hunter22' postgresql://u:dbpass123@h/db"
    _install_crashing_route("/__phase3b_crash", message)
    caplog.set_level(logging.ERROR)
    response = TestClient(main.app, raise_server_exceptions=False).get("/__phase3b_crash")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error" and body["request_id"] == response.headers["X-Request-ID"]
    for leak in (SECRET, "SELECT", "hunter22", "dbpass123", "RuntimeError", "Traceback"):
        assert leak not in response.text
    assert response.headers["X-Frame-Options"] == "DENY"
    # Diagnostics stay server-side, tagged with the request id, credentials redacted.
    assert body["request_id"] in caplog.text and "RuntimeError" in caplog.text
    assert "hunter22" not in caplog.text and "dbpass123" not in caplog.text


def test_explicit_errors_are_unchanged(server):
    manager = login("manager1")
    assert manager.get("/sessions/" + "0" * 32 + "/score").json() == {"detail": "session not found"}
    assert manager.post("/sessions", json={}).status_code == 422
    assert manager.get("/admin/users").status_code == 403


def test_service_errors_now_carry_the_request_id(server, monkeypatch):
    async def down(*args, **kwargs):
        raise RuntimeError("down")

    manager = login("manager1")
    session_id = start_session(manager, SCENARIO)["id"]
    monkeypatch.setattr(main.dialog_provider, "respond", down)
    response = manager.post(f"/sessions/{session_id}/turns", json={"text": "x"})
    assert response.status_code == 502
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


# ================================================================ redaction


@pytest.mark.parametrize(
    "raw,secret",
    [
        ("Authorization: Bearer abcdefgh12345", "abcdefgh12345"),
        ("headers={'x-api-key': 'k-12345678'}", "k-12345678"),
        ("xi-api-key=eleven-123456", "eleven-123456"),
        ("Token deepgram-secret-999", "deepgram-secret-999"),
        ("key sk-ant-api03-ABCDEFGHIJKL", "sk-ant-api03-ABCDEFGHIJKL"),
        ("eleven sk_0123456789abcdef0123", "sk_0123456789abcdef0123"),
        ("postgresql://neondb_owner:npg_abc123XYZ@host/db", "npg_abc123XYZ"),
        ("Cookie: avt_session=uid.123.sig", "uid.123.sig"),
        ("password=hunter22", "hunter22"),
    ],
)
def test_redact_patterns(raw, secret):
    cleaned = redact(raw)
    assert secret not in cleaned and REDACTED in cleaned


def test_redact_configured_secret_values_and_length(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", SECRET)
    assert redact(f"invalid key {SECRET} rejected") == f"invalid key {REDACTED} rejected"
    assert len(redact("x" * 10_000)) == 2000  # stored diagnostics are capped
    assert len(redact("x" * 10_000, max_length=None)) == 10_000  # log tracebacks keep their last line
    assert redact("plain provider timeout after 30s") == "plain provider timeout after 30s"


def test_stored_scoring_error_is_redacted(server, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "anthropic_api_key", SECRET)

    async def leaky(*args, **kwargs):
        raise RuntimeError(f"401 for key {SECRET}; Authorization: Bearer {SECRET}; x-api-key: {SECRET}")

    manager = login("manager1")
    session_id = start_session(manager, SCENARIO)["id"]
    ok(manager.post(f"/sessions/{session_id}/turns", json={"text": "Добрый день"}))
    monkeypatch.setattr(main.scoring_provider, "verify_claims", leaky)
    ok(manager.post(f"/sessions/{session_id}/finish"))
    assert ok(manager.post(f"/sessions/{session_id}/score-run"))["status"] == "finish_error"

    async def stored():
        async with SessionLocal() as db:
            return (await db.get(SessionModel, session_id)).scoring_error

    error = asyncio.run(stored())
    assert SECRET not in error and REDACTED in error and error.startswith("401 for key")
    assert SECRET not in manager.get(f"/sessions/{session_id}/score").text
