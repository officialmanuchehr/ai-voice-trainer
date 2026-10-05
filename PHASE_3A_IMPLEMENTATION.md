# Phase 3A — AI service failure handling and session consistency

**Date:** 2026-10-05 · **Base:** Phase 2 commit `d57d772` · **Scope:** plan items A0-3 (transcript ↔ screen consistency) and A0-4 (no raw provider errors to users), for Deepgram, DeepSeek, ElevenLabs and Anthropic.
**Git:** uncommitted, for review. Nothing pushed or merged.

## Core invariant
**What the user sees equals what is stored in the session transcript.**

Server side:
- A turn pair (manager + AI client) is committed only after the AI client has answered.
- A failure before that commits nothing.
- Text-to-speech runs after the commit and can't undo it.

Client side: after any failed turn the chat is redrawn from `GET /transcript`.

## Behaviour before → after

| Failure | Before | After |
|---|---|---|
| **DeepSeek, text turn** | Unhandled 500, plain text. Transcript unchanged (the transaction rolled back). The UI kept the manager's bubble on screen although it wasn't stored, and the input was cleared. | 502 `dialog_unavailable` with a safe message. Nothing stored. The UI removes the pending bubble, redraws from the transcript, puts the text back in the input, and offers **Повторить**. Retrying adds exactly one pair. |
| **Deepgram (STT), voice turn** | Unhandled 500. Nothing stored. | 502 `stt_unavailable`. Nothing stored, the AI client is **not called**, audio discarded as before (never persisted). The user records again or types. |
| **STT ok → DeepSeek fails** | Unhandled 500; the recognised text was lost, so the manager had to repeat the recording. | 502 `dialog_unavailable` **plus `manager_text`**. Nothing stored. The UI puts the recognised text in the input with **Повторить**, which resends it as text, with no re-recording and no re-transcription. |
| **ElevenLabs (TTS), voice turn** | Both turns already committed, then a 500. The UI never showed the stored pair, and a retry **duplicated** it. | **200** with the committed `manager_text` and `ai_client_text`, `ai_client_audio_base64: null`, `audio_error: "audio_unavailable"`. The UI shows the reply with "Озвучка временно недоступна — прочитайте ответ клиента". The conversation continues in text. |
| **ElevenLabs, replay `GET /turns/{i}/audio`** (text turns) | Unhandled 500; playback failed silently. | 502 `audio_unavailable`; the UI shows the same "озвучка недоступна" note. Replay never writes to the transcript. |
| **Anthropic (claim check or scoring)** | `finish_error`, and `/score` returned `detail: str(exc)`, the raw provider message. | `finish_error` (unchanged). `/score` returns only `{status: "finish_error", code: "scoring_unavailable", detail: <safe message>}`, with no total, breakdown or feedback. The raw error goes to the server log and the server-side `scoring_error` column only. Retry via **Завершить и получить оценку** is unchanged. The 270 s timeout path is covered too. |
| **Lost response / network drop** (any turn) | "сеть недоступна (…)"; if the server had committed, a retry duplicated the pair. | Friendly message. The UI redraws from the transcript: if the turn **was** stored it's shown and nothing is resent; if not, the text is restored for retry. |
| **Any other server error without a safe detail** | UI showed "Ошибка: HTTP 500". | UI shows "Сервис временно недоступен. Попробуйте ещё раз." |

## Transaction / persistence behaviour
- **Text and voice share one path** (`_process_manager_turn`): the manager turn is *flushed* (to get its index) and the AI client is called. Only on success are both turns committed together. On any provider failure the request's DB session closes without committing, so neither turn exists.

  This was already true before Phase 3A. Phase 3A makes it explicit and tested, and maps the failure to a safe error. **No transaction redesign or schema change was needed.**
- **Speech-to-text** runs before the DB is touched. **Text-to-speech** runs after the commit and is non-fatal.
- **Retry needs no idempotency key**, for two reasons:
  - The server only ever stores complete pairs.
  - The client reconciles with the stored transcript before offering a resend.

  A server-side key would need a schema change, which is out of scope for this phase.
- **Audio** is still read into memory, sent to STT and deleted. The test scans the SQLite file for a unique byte marker from the uploaded audio and finds nothing.

## Client-facing error codes (new)
All are HTTP 502, body `{"code": "...", "detail": "<Russian message>"}`, matching the existing `{detail}` style plus the `code` field introduced in Phase 1. `/score` returns its `scoring_unavailable` code and message inside its normal 200 status response.

| Code | Where | Extra |
|---|---|---|
| `stt_unavailable` | `POST /sessions/{id}/voice-turn` | — |
| `dialog_unavailable` | `POST /sessions/{id}/turns`, `POST /sessions/{id}/voice-turn` | `manager_text` on voice turns (STT succeeded) |
| `audio_unavailable` | `GET /sessions/{id}/turns/{i}/audio` (502); `audio_error` field in a 200 voice-turn response | — |
| `scoring_unavailable` | `GET /sessions/{id}/score` while `finish_error` | — |

**Mechanism:** one small exception type `ServiceUnavailable(code, **extra)`, one exception handler, and `_call_service(code, call)`, which wraps each provider call. There's no new error framework. Provider failures are logged with `logger.exception` (logger `app`), so diagnostics stay server-side only.

**Unchanged:** empty speech recognition still returns 400 "пустая реплика — речь не распознана", and all other 4xx responses (ownership, status, validation) are as before.

## Files changed

| File | Change |
|---|---|
| `app/main.py` | `SERVICE_MESSAGES`, `ServiceUnavailable`, `_call_service`, exception handler; dialog, STT and audio replay wrapped; voice-turn TTS non-fatal with `audio_error`; voice-turn returns `manager_text` on dialog failure; scoring failure logged and `/score` returns a code plus safe message |
| `static/app.js` | `api()`: friendly network and 5xx messages (no raw "HTTP 500"), errors carry `status`, `code`, `data` |
| `static/index.html` | Minimal: pending bubble while sending, `syncChat()` redraws from the transcript after a failure, `turnFailed()` restores unsent text and adds **Повторить**, voice `audio_error` note, audio-player error note. No layout or design change. |
| `tests/test_phase3a.py` | New, 11 tests |
| `PILOT_READINESS_PLAN.md` | A0-3 and A0-4 marked done |

**Unchanged (zero diff):**
- `app/prompts.py` and all providers;
- `app/scoring_math.py`, `app/security.py`, `app/content.py`, `app/routers/*`, `app/models.py`;
- `seed/`, `vercel.json`, `requirements.txt`;
- all existing tests.

## Tests added (`tests/test_phase3a.py`, 11)

Every injected failure raises `"SECRET_PROVIDER_ERROR_123 … Authorization: Bearer sk-SECRET-KEY-456"`. After each one, a sweep checks that the marker, the fake key, "Authorization", "Traceback" and "RuntimeError" don't appear in:
- the failing response;
- `/transcript` and `/score` for the owner, team lead and admin;
- `/me/sessions`, `/admin/audit` and `/dashboard/data`.

| Test | Proves |
|---|---|
| Text: dialog failure | 502 `dialog_unavailable`, safe; neither turn stored; retry adds exactly one pair with contiguous indexes and the original text |
| Text: session stays active | Status `active` after a failure; nothing to finish (unchanged 400) |
| Voice: STT failure | 502 `stt_unavailable`; AI client not called; transcript unchanged; audio marker absent from the DB file |
| Voice: STT ok, dialog fails | 502 `dialog_unavailable` with the recognised `manager_text`; no partial pair; resending it as text gives exactly one pair; no audio persisted |
| Voice: empty recognition | Unchanged 400, nothing stored |
| TTS failure | 200 with committed text, `audio_error`, no audio; transcript has exactly the pair; replay → 502 `audio_unavailable` without touching the transcript; the session continues in text; after recovery replay works, still no new turns |
| Voice success | Unchanged (no `audio_error`, pair stored) |
| Scoring failure ×2 (claim check, scoring) | `finish_error`; `/score` is exactly `{session_id, status, code, detail}` with no partial result; transcript intact; retry → `finished`, same scenario and KB versions as bound |
| Scoring timeout | Also returns `scoring_unavailable` |
| Frontend | `api()` no longer renders raw "HTTP …"; errors carry `code`; training page has transcript reconciliation and handles `manager_text` / `audio_error` |

**Tests catch the old behaviour:** run against the Phase 2 code they give **9 failed, 2 passed**. The 2 that pass are the "unchanged" checks.

## Test results
```
pytest                       366 passed
pytest tests                 366 passed
test_phase3a.py               11 passed
test_access.py                43 passed
test_phase1.py                22 passed
test_phase1b.py               51 passed
test_phase2_*.py             239 passed (each file alone, all green)
3A first, then reversed      366 passed
shuffled order               366 passed
```
Offline: stub providers, temporary SQLite, no credentials, no paid model calls.

## Database / schema impact
None.

## Deployment / environment impact
None: no new env var, dependency or infrastructure change. Provider errors now appear in the server log (Vercel function logs) via Python `logging` at ERROR level.

## Known limitations
- **No automatic server-side retry** of a failed provider call. Retry is user-initiated, and safe, because nothing partial is stored. The plan's optional "one server-side retry" is left for Phase 3B if wanted.
- **Provider timeouts are unchanged** (httpx 30 s each). A voice turn can therefore take up to about 90 s in the worst case before the error appears, and the UI shows the existing "Клиент думает…" state meanwhile.
- **Frontend behaviour was verified by code inspection and the static-asset test only**, not in a real browser: there is no browser runner in this repo. Manual check recommended: kill the network or point a provider at a bad key, then send text and voice turns.
- **Stub TTS returns empty audio**, so in local stub mode the "озвучка недоступна" note appears after text turns. Real ElevenLabs is unaffected.
- **`scoring_error` still stores the raw exception text in the DB.** It's never returned by any endpoint and is kept for diagnostics. Whether the DB should hold it is part of the retention decision (B-9).

## Existing behaviour intentionally left unchanged
- Session ownership and RBAC.
- Scenario and KB version binding.
- Hidden-field protection.
- Scoring methodology, rubric, weights, cap, prompts.
- Phase 1 and 1b safety rules.
- Scoring retry path.
- Empty-recognition 400.
- Audio never persisted.
- No login throttling or security headers (Phase 3B).
