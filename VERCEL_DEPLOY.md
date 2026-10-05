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

## Current state (updated 2026-10-05)

- Vercel project **`officialmanuchehr-9511s-projects/ai-voice-trainer`**, linked
  to this GitHub repo. Production alias: `https://ai-voice-trainer-weld.vercel.app`.
- **Neon Postgres** `neon-blue-envelope` provisioned via the Vercel marketplace
  integration and connected — it set `DATABASE_URL` (+ `POSTGRES_*`, `PG*`) on
  all environments.
- **Block 4 (users/roles) is live.** `SECRET_KEY`, `INITIAL_ADMIN_USERNAME`,
  `INITIAL_ADMIN_PASSWORD` set (production + development), `init_db` run
  against Neon, admin user created. `BASIC_AUTH_*` is still on in production
  as an outer gate, so users log in twice (browser prompt, then `/login`).
- Functions run on **fluid compute with a 300s limit** (project default,
  confirmed on the deployment: `functionTimeout: 300`).
- **Verified live (2026-10-05):** login, admin, dashboard, text turn (DeepSeek),
  TTS audio (ElevenLabs), full voice turn (Deepgram → DeepSeek → ElevenLabs).
- **Known bad:** `ANTHROPIC_API_KEY` is rejected by the API (401), so scoring
  ends in `finish_error`. Set a valid key and redeploy:
  ```
  vercel env rm ANTHROPIC_API_KEY production --yes
  printf '%s' 'sk-ant-...' | vercel env add ANTHROPIC_API_KEY production
  vercel --prod --archive=tgz
  ```

## Upgrading the live deployment to users/roles (Block 4)

The app now has its own login, so the existing deployment needs three new env
vars and one `init_db` run before (or right after) deploying this code:

```
python3 -c "import secrets; print(secrets.token_urlsafe(48))" | vercel env add SECRET_KEY production
printf '%s' 'admin'          | vercel env add INITIAL_ADMIN_USERNAME production
printf '%s' '<strong pass>'  | vercel env add INITIAL_ADMIN_PASSWORD production
# repeat for preview/development as needed

DATABASE_URL='postgresql://…' SECRET_KEY=… INITIAL_ADMIN_USERNAME=admin \
  INITIAL_ADMIN_PASSWORD='<strong pass>' python scripts/init_db.py
vercel --prod --archive=tgz
```

`init_db` adds the new tables/columns, versions the existing scenario and KB as
published, inserts the three new draft products and the new draft scenarios,
and creates the admin. Existing sessions are kept (they have no user; admins
can still open them). Without `SECRET_KEY` the app refuses to log anyone in on
Postgres. Basic Auth still works as an optional outer gate; once real users
exist you can drop `BASIC_AUTH_*` to avoid the double login.

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

1. **Function timeout = 300s** (fluid compute default). A full `claude`
   scoring run is two sequential streamed calls; `score-run` caps it at 270s
   (`_SCORING_BUDGET_SECONDS` in `app/main.py`) so an overrun is recorded as
   `finish_error` the user can retry, instead of the function being killed
   with the session stuck in `scoring`. The browser stops polling after 6 min.

2. **4.5 MB request/response body limit.** `/sessions/{id}/voice-turn` uploads
   audio and returns base64 audio; long turns with a real TTS/STT provider can
   exceed this and get a 413. The text endpoints (`/turns`) are unaffected.

3. **No background execution after a response.** Anything that must outlive a
   request has to be its own request (that is what `score-run` is). Don't
   reintroduce `BackgroundTasks` for work that matters.

4. **Cold starts** re-import the app and re-open a DB connection (~1–2s on the
   first request after idle).
