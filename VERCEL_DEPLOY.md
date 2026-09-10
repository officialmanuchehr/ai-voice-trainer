# Deploying to Vercel

This app was originally built for a container platform (see `Dockerfile` /
`railway.json`). It now also runs on Vercel's Python serverless runtime. The
pieces that make that work:

| Piece | What it does |
| --- | --- |
| `api/index.py` | ASGI entrypoint Vercel serves. Puts the repo root on `sys.path` and re-exports `app.main:app`. |
| `vercel.json` | Legacy `builds` + `routes` (`dest: api/index.py`) so all paths reach the function with the **original** request path — `rewrites`/`destination` rewrites the path to `/api/index` and every route 404s. `includeFiles` bundles `app/ seed/ static/`. |
| `scripts/init_db.py` | Creates tables + runs migrations + loads seed data. Run manually — the app does **not** do this on startup in serverless (`AUTO_INIT_DB=false`). |
| `POST /sessions/{id}/score-run` | Runs scoring synchronously (~60s+). The browser fires it without waiting and polls `GET /sessions/{id}/score` for the result. Replaces the old in-process `BackgroundTask`, which a serverless function kills the moment it responds. |

## Current state (deployed 2026-09-10)

- Vercel project **`officialmanuchehr-9511s-projects/ai-voice-trainer`**, linked
  to this GitHub repo. Production alias: `https://ai-voice-trainer-weld.vercel.app`.
- All env vars set for production/preview/development **except `DATABASE_URL`**:
  `AUTO_INIT_DB=false`, `BASIC_AUTH_USERNAME`/`BASIC_AUTH_PASSWORD` (generated),
  and the four providers + keys mirrored from local `.env`
  (`deepgram`/`deepseek`/`claude`/`elevenlabs`).
- `GET /health` → 200, `GET /` → 401 then 200 with Basic Auth. Any DB-backed
  route 500s until step 1 below is done.

**Remaining: steps 1 and 4** (provision Postgres, then run `init_db.py`). Step 1
needs a one-time browser click — accepting a storage provider's marketplace
terms — which is why it wasn't automated.

## 1. Provision a Postgres database

Serverless has no persistent disk, so the default SQLite file will not work —
you need external Postgres. Any of Neon / Supabase / Prisma Postgres is fine.

**Use the pooled / transaction-mode connection string** (Neon's "-pooler" host,
Supabase port `6543`). `app/database.py` already sets `NullPool` +
`statement_cache_size=0` so this works.

Fastest path, since the project is already linked to Vercel:

```
# one-time: open the URL it prints and accept the provider's marketplace terms
vercel integration add neon
# then re-run — it provisions the DB, sets DATABASE_URL on all environments,
# connects it to the project, and pulls the value locally:
vercel integration add neon --environment production --environment preview --environment development
```

(Swap `neon` for `supabase` or `prisma/prisma-postgres` if you prefer.) Or
create a DB in that provider's own dashboard and set `DATABASE_URL` yourself
with `vercel env add`.

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

Already done once. To redeploy after adding `DATABASE_URL` (or any code change):

```
vercel --prod --archive=tgz
```

Python 3.12 is picked automatically; `requirements.txt` is installed by the
build. `builds` in `vercel.json` means Project Settings build config is ignored.

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

1. **Function timeout = 60s (plan default).** A full `claude` scoring run is
   two sequential streamed calls and can exceed 60s. If scoring times out, the
   session stays `scoring`; after 10 min `score-run` can re-claim it (the
   browser will have stopped polling by then — the user clicks finish again).
   The legacy `builds` config in `vercel.json` does **not** honour a
   `maxDuration` key, so to raise the cap on Pro you switch the function to the
   modern `functions` config — but that reintroduces the path-rewrite bug
   above, so it also needs `api/index.py` moved to a real catch-all
   (`api/[[...path]].py` is not supported for Python; the practical route is a
   small ASGI shim that strips the `/api/index` prefix). For serious use, Pro +
   that rework is recommended.

2. **4.5 MB request/response body limit.** `/sessions/{id}/voice-turn` uploads
   audio and returns base64 audio; long turns with a real TTS/STT provider can
   exceed this and get a 413. The text endpoints (`/turns`) are unaffected.

3. **No background execution after a response.** Anything that must outlive a
   request has to be its own request (that is what `score-run` is). Don't
   reintroduce `BackgroundTasks` for work that matters.

4. **Cold starts** re-import the app and re-open a DB connection (~1–2s on the
   first request after idle).
