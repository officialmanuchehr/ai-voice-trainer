# Deploying to Vercel

This app was originally built for a container platform (see `Dockerfile` /
`railway.json`). It now also runs on Vercel's Python serverless runtime. The
pieces that make that work:

| Piece | What it does |
| --- | --- |
| `api/index.py` | ASGI entrypoint Vercel serves. Puts the repo root on `sys.path` and re-exports `app.main:app`. |
| `vercel.json` | Rewrites every path to that one function, bundles `app/ seed/ static/`, sets `maxDuration`. |
| `scripts/init_db.py` | Creates tables + runs migrations + loads seed data. Run manually — the app does **not** do this on startup in serverless (`AUTO_INIT_DB=false`). |
| `POST /sessions/{id}/score-run` | Runs scoring synchronously (~60s+). The browser fires it without waiting and polls `GET /sessions/{id}/score` for the result. Replaces the old in-process `BackgroundTask`, which a serverless function kills the moment it responds. |

## 1. Provision a Postgres database

Serverless has no persistent disk, so the default SQLite file will not work —
you need external Postgres. Any of Neon / Supabase / Vercel Postgres is fine.

**Use the pooled / transaction-mode connection string** (Neon's "-pooler" host,
Supabase port `6543`). `app/database.py` already sets `NullPool` +
`statement_cache_size=0` so this works.

## 2. Set environment variables (Vercel → Project → Settings → Environment Variables)

Required:

| Var | Value |
| --- | --- |
| `DATABASE_URL` | Postgres URL from step 1. `postgres://…` or `postgresql://…` is fine — `app/config.py` rewrites it to `postgresql+asyncpg://…`. |
| `AUTO_INIT_DB` | `false` |
| `BASIC_AUTH_USERNAME` | pick one — the whole app is behind HTTP Basic Auth |
| `BASIC_AUTH_PASSWORD` | pick one |

Provider selection (default `stub` everywhere — set the ones you actually use):

| Var | Notes |
| --- | --- |
| `STT_PROVIDER` | `stub` or `deepgram` (`DEEPGRAM_API_KEY`) |
| `DIALOG_PROVIDER` | `stub` or `deepseek` (`DEEPSEEK_API_KEY`, optional `DEEPSEEK_MODEL`) |
| `SCORING_PROVIDER` | `stub` or `claude` (`ANTHROPIC_API_KEY`) |
| `TTS_PROVIDER` | `stub` or `elevenlabs` (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`) |

## 3. Deploy

```
npm i -g vercel
vercel            # first run: link/create the project
vercel --prod
```

Project settings: Framework preset **Other**, Python version **3.12**. No build
command needed; Vercel installs `requirements.txt` automatically.

## 4. Initialise the database (once, and after any schema/seed change)

```
DATABASE_URL='postgresql://…' python scripts/init_db.py
```

Run it from a machine with the repo checked out and `requirements.txt` installed
(your local venv is fine). It is idempotent.

## 5. Verify

- `GET /health` → `{"status":"ok"}` (the only route not behind Basic Auth)
- Open `/`, log in with the Basic Auth credentials, run a session, click finish.

---

## Known limitations on Vercel

1. **`maxDuration` = 60s on Hobby.** A full `claude` scoring run is two
   sequential streamed calls and can exceed 60s. If scoring times out, the
   session stays `scoring`; after 10 min `score-run` can re-claim it (the
   browser will have stopped polling by then — the user clicks finish again).
   **On Pro, raise `maxDuration` to `300` in `vercel.json`** and this stops
   being an issue. For serious use, Pro is recommended.

2. **4.5 MB request/response body limit.** `/sessions/{id}/voice-turn` uploads
   audio and returns base64 audio; long turns with a real TTS/STT provider can
   exceed this and get a 413. The text endpoints (`/turns`) are unaffected.

3. **No background execution after a response.** Anything that must outlive a
   request has to be its own request (that is what `score-run` is). Don't
   reintroduce `BackgroundTasks` for work that matters.

4. **Cold starts** re-import the app and re-open a DB connection (~1–2s on the
   first request after idle).
