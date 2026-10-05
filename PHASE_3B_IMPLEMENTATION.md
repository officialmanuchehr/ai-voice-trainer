# Phase 3B — Pilot security hardening: implementation record

**Date:** 2026-10-05 · **Base:** Phase 3A commit `7e390f0` · **Scope:** login throttling, security headers, API docs off in production, safe unexpected errors, request IDs, redaction of stored/logged diagnostics.
**Git:** uncommitted, for review. Nothing pushed, merged or deployed.

## 1. Security controls implemented

| Control | Where |
|---|---|
| DB-backed login throttling + failed-login / throttle audit events | `app/login_guard.py`, `app/routers/auth.py`, `app/models.py` (`LoginAttempt`) |
| Timing-equalised login for unknown usernames | `app/login_guard.py` (`password_matches`) |
| Security headers on every response | `app/http_security.py` (`RequestContextMiddleware`) |
| Server-generated request ID (header, error bodies, logs) | `app/http_security.py`, `app/main.py` |
| API docs only in local development | `app/main.py`, `app/config.py` (`api_docs`) |
| Generic JSON 500 for unexpected exceptions | `app/main.py` (`_unexpected_error`) |
| Redaction of stored scoring diagnostics and `app` logs | `app/redact.py`, `app/main.py` |
| Request ID shown with server errors in the UI | `static/app.js` (1 line) |

## 2. Login throttle design
- **Policy:** the plan's value. **5 failed logins** for the same **(normalised username, client IP)** within a **15-minute sliding window**. The next attempt gets **429** `{"code": "login_throttled", "detail": "Слишком много неудачных попыток входа. Попробуйте снова через N мин.", "request_id": …}` and a `Retry-After` header (seconds until the oldest counted failure expires). Configurable via `LOGIN_MAX_FAILURES` / `LOGIN_WINDOW_MINUTES`.
- **Order of checks:**
  1. Throttle, **before** the password is examined. A throttled response is therefore identical for right and wrong passwords and for existing and non-existing usernames.
  2. Password.
  3. On failure: record it, audit, return 401 (unchanged message).
  4. On success: delete that key's failures and log in.
- **Normalised username:** `strip().lower()`, used only for the throttle key. Login matching itself is unchanged (case-sensitive).
- **Storage:** table `login_attempts(id, key_hash, created_at)`. `key_hash` = HMAC-SHA256(`SECRET_KEY`, "username|ip"). No username, IP or password is stored there. Rows older than the window are purged on each new failure.
- **Unknown usernames:** treated exactly like wrong passwords: same 401, same counter, same 429. Previously an unknown username skipped PBKDF2 and answered measurably faster (a username-existence timing leak). It now runs one dummy PBKDF2 verification. *Found while implementing; fixed because it falls under "do not reveal whether the username exists".*
- **Inactive users** with a correct password still get the same 401 and count as failures (unchanged outward behaviour).

## 3. Trusted client-IP model
- **Setting:** `CLIENT_IP_HEADER` names the header written by a **trusted** proxy.
  - **Vercel:** per Vercel's request-headers documentation, Vercel *overwrites* `X-Forwarded-For` "to prevent IP spoofing", and `x-real-ip` is identical to it. So on Vercel set `CLIENT_IP_HEADER=x-real-ip`.
  - **Parsing:** the value must parse as an IP address (first comma-separated entry); anything else falls back to the TCP peer. A garbage header can't create fresh throttle keys (tested).
- **When unset (default):** the direct TCP peer address is used. Client-supplied headers are **never** trusted by default, so they can't be used to dodge the throttle (tested).
  - On Vercel without the setting, the peer is Vercel's internal address. Throttling still works, but effectively **per username** (all clients share one "IP"). That's safe but coarser: an attacker could temporarily lock a known username.
- **Never set** `CLIENT_IP_HEADER` behind a proxy that passes client headers through unchanged (e.g. a plain container without a rewriting proxy).

## 4. DB / schema changes
- **One new table,** `login_attempts`, with indexes on `key_hash` and `created_at`. It's created by the existing `init_db` (`Base.metadata.create_all`); there is no Alembic in this project, so none was added.
- **Verified:** running `scripts/init_db.py` against a copy of a pre-3B database added the table and both indexes and left existing users and sessions untouched.
- **No changes** to existing tables.

## 5. Security headers / CSP
Set on every response by the outermost middleware: pages, static assets, API JSON, Basic Auth 401s. The unexpected-error 500 sets them itself, because it runs outside the middleware stack.

| Header | Value |
|---|---|
| Content-Security-Policy | `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'` |
| X-Content-Type-Options | `nosniff` |
| X-Frame-Options | `DENY` |
| Referrer-Policy | `same-origin` |
| Permissions-Policy | `microphone=(self), camera=(), geolocation=(), payment=(), usb=(), interest-cohort=()` |
| X-Request-ID | 32-hex, server-generated |

**Why this CSP:**
- The current pages have one inline `<script>` each and 43 inline `style=""` attributes, hence `'unsafe-inline'` for scripts and styles.
- There are no inline event handlers and no external resources (verified for all 5 pages by test).
- Client audio plays from `data:` URLs.
- **Microphone stays allowed for this origin.**
- Removing `'unsafe-inline'` requires moving the inline scripts into modules, which is planned with the Phase 4 frontend restructuring.

**HSTS** is **not** set by the app: production on Vercel already sends `strict-transport-security: max-age=63072000; includeSubDomains; preload` (checked live). For self-hosting, configure HSTS at the TLS terminator.

`/docs` and `/redoc` (development only) are served without CSP so Swagger/ReDoc can load their CDN assets. Their other headers still apply.

## 6. API docs
- `/docs`, `/redoc` and `/openapi.json` return **404 in production** by default. Default rule: enabled only when `DATABASE_URL` is SQLite (local development, the same "local dev" signal the app already uses for its dev cookie secret).
- `API_DOCS=true|false` forces either way.
- No production env change is needed: production runs on Postgres, so docs are off.

## 7. Unexpected errors
- **Any exception not handled more specifically** now returns **500** `{"code": "internal_error", "detail": "Внутренняя ошибка сервера…", "request_id": …}` with the security headers and `X-Request-ID`.
- **No traceback,** exception class, SQL, provider payload or environment data reaches the client (tested with SQL, a DB URL with password and a configured key in the exception).
- **The full traceback is logged server-side** with the request ID, redacted.
- **Unchanged:** explicit errors (400/401/403/404/409/422/429) and Phase 3A's 502 service errors. The 502 bodies now also carry `request_id`.

## 8. Request ID
- **Generation:** server-generated UUID4 hex per request, **never taken from the client** (an incoming `X-Request-ID` is ignored, as tested).
- **Where it goes:** the `X-Request-ID` header, `request_id` in 5xx/429 bodies, and the `[request_id=…]` tag on every `app` log line (service failures, scoring failures, unhandled errors).
- **Contents:** no user or session information.
- **In the UI:** server errors append "(код запроса: …)" so a user can report it.

## 9. Diagnostic-error sanitisation
- **Audited:** the only diagnostic text persisted is `sessions.scoring_error` (the scoring exception message), and it's never returned to clients since Phase 3A. It now passes through `redact()` before storage. Nothing else stores exception text (audit details don't).
- **What `redact()` removes:**
  - every configured secret value (the four provider keys, `SECRET_KEY`, Basic Auth password, initial admin password, the DB password);
  - `Bearer|Token|Basic <value>`;
  - `authorization|x-api-key|xi-api-key|api_key|cookie|password|secret` `: or =` value;
  - `sk-…`, `sk_…`, `npg_…` key shapes;
  - credentials in `scheme://user:pass@` URLs;
  - `avt_session=` cookies.
- **Limits:** stored text is capped at 2,000 characters. Diagnostics are otherwise kept: a stored error still reads, for example, "401 for key [REDACTED]…".
- **Logs:** the same redaction runs on every record of the `app` logger (message and traceback, without truncation, so the final exception line survives).
- **Existing rows:** production `scoring_error` values written before this phase aren't rewritten. The earlier invalid-key failures were Anthropic messages ("invalid x-api-key") that don't contain the key.

## 10. Security audit events

| Event | When | Details |
|---|---|---|
| `auth.login_failed` | every failed login (bounded by the throttle) | `username` (only if the account exists, so a password typed into the username field is never stored), `ip` |
| `auth.login_throttled` | **once**, at the failure that reaches the limit | `username` / `ip` as above, `failures` |
| `auth.login` | successful login (existing) | now `{"previous_failures": N}` when there were recent failures |

Throttled (blocked) attempts aren't audited individually, so an attacker can't flood the journal. Passwords never appear in the DB, the audit log or `app` logs (tested with sentinels).

## 11. Tests added (`tests/test_phase3b.py`, 42)

| Area | Tests |
|---|---|
| Throttling | Below threshold still logs in · threshold → 429 even with the right password, `Retry-After`, `login_throttled` · success resets the counter · unknown vs existing username: identical 401s and 429s · unknown username runs the PBKDF2 check · other usernames unaffected · username normalisation shares the counter · trusted IP header separates clients · untrusted header can't dodge · garbage IP header falls back to the peer · window expiry unlocks · password and username typos never in the DB file, audit or logs · audit: 5 `login_failed`, exactly 1 `login_throttled`, blocked attempts not audited, `previous_failures` on success, unknown username stored as null |
| Headers | All headers on login page, training page, static JS, `/health`, a 401 API response, an authenticated API response · CSP fits every page (no external resources; required directives present) · Basic Auth 401 carries headers · request IDs unique, server-generated, client value ignored |
| API docs | Available in local development (3) · 404 in production by default, explicit opt-in works (3) |
| Unexpected errors | Generic 500 with `internal_error`, `request_id` = header; no secret, SQL, DB password, exception class or traceback in the response; log has request ID and class but not the credentials · explicit 404/422/403 unchanged · 502 service errors carry `request_id` |
| Redaction | 9 credential shapes · configured secret values, length cap, untouched plain text · stored `scoring_error` redacted but still informative, and not exposed via `/score` |

## 12. Test results
```
pytest                       408 passed
pytest tests                 408 passed
test_phase3b.py               42 passed
test_phase3a.py               11 passed
test_phase2_*.py             239 passed (each file alone)
test_phase1b.py               51 passed
test_phase1.py                22 passed
test_access.py                43 passed
3B first, then reversed      408 passed
shuffled order               408 passed
```
Offline: stub providers, temporary SQLite, no credentials, no paid calls. Test count: 366 → 408.

## 13. Deployment requirements
1. **Run `scripts/init_db.py` against production before deploying this code.** It creates `login_attempts`, is additive and idempotent, and old code ignores the table. Deploying first would make every login attempt fail with 500 until the table exists.
2. **Set `CLIENT_IP_HEADER=x-real-ip`** in Vercel (production, plus preview if used). Without it, throttling works per username only (see §3).
3. **No other env change:** docs are off automatically on Postgres, and the headers need no configuration.
4. **Keep production logging at INFO or WARNING.** At DEBUG, the SQLAlchemy/aiosqlite drivers log raw SQL parameters, including typed usernames. The app's own `app` logger is redacted; third-party loggers aren't.

## 14. Environment variables (new, all optional)

| Variable | Default | Purpose |
|---|---|---|
| `CLIENT_IP_HEADER` | empty (TCP peer) | Trusted client-IP header; `x-real-ip` on Vercel |
| `LOGIN_MAX_FAILURES` | 5 | Throttle limit |
| `LOGIN_WINDOW_MINUTES` | 15 | Throttle window |
| `API_DOCS` | unset (on for SQLite, off otherwise) | Force docs on or off |

## 15. Rollback
- **Code rollback** to `7e390f0` is safe: older code ignores the `login_attempts` table, which can stay or be dropped.
- **No other data changes.**
- **Headers can't be turned off by config.** If the CSP breaks a page in production, the fix is a code change to `CONTENT_SECURITY_POLICY` in `app/http_security.py` (single constant).

## 16. Known limitations
- **`'unsafe-inline'`** for scripts and styles until the inline scripts move to modules (Phase 4).
- **Distributed guessing isn't stopped:** throttling is per (username, IP), so many IPs against one username, or one IP spraying many usernames, isn't limited by a global counter. That's acceptable for an internal pilot behind Basic Auth; a global per-username cap can be added if the bank's security review asks for it.
- **Username lockout by an attacker:** an attacker who knows a username can make it unusable from *their own* IP only. Without `CLIENT_IP_HEADER` on Vercel, from everywhere for 15 minutes (see §3).
- **Logout and password reset still don't revoke existing cookies** (plan A2-3, not in this phase).
- **Redaction covers only stored scoring errors and the `app` logger.** Uvicorn and Vercel framework logs of unhandled errors aren't filtered.
- **The browser behaviour of the new headers wasn't checked in a real browser** (no browser runner). The CSP was derived from the page sources and checked by test. A manual check of microphone, audio playback, dashboard charts and admin dialogs after deploy is recommended.
