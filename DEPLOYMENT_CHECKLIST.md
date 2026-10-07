# Controlled-pilot deployment checklist

Tick each box with the date and the role that checked it. **Don't deploy until every "before deploy" box is ticked.** Never write secret values into this file, tickets or chat.

## A. Approvals (before deploy)
- [ ] **Commit:** the approved commit hash and tag recorded (e.g. `pilot-v1`), with CI green on that commit.
- [ ] **Bank decisions:** every "must decide before pilot" item in `BANK_PILOT_DECISIONS.md` is decided in writing (providers, DeepSeek, regions, hosting, retention, security/network).
- [ ] **Content:** the pilot content in `PILOT_CONTENT_GATE.md` is approved by Product + Compliance (bank roles); **C-9 resolved** or merchant content excluded.
- [ ] **Real-provider gate:** G1 and G2 passed on staging (`PHASE_9_LAUNCH_READINESS.md` §11), with latency recorded.

## B. Environment (Vercel project → Production; names only)
- [ ] `DATABASE_URL` points to the **pilot** database and is **not shared with Preview**. Give Preview its own database or branch, or disable preview deployments.
  - 2026-10-08: git preview deployments are disabled in `vercel.json` (`git.deploymentEnabled`: only `main` deploys). `DATABASE_URL` is still assigned to Preview by the Neon integration, so a manual `vercel deploy` without `--prod` would still reach the pilot database. Don't make CLI preview deploys; delete the older preview deployments.
- [ ] `SECRET_KEY`: long random value, production-only.
- [ ] `STT_PROVIDER=deepgram`, `DIALOG_PROVIDER=deepseek` (or the approved replacement), `SCORING_PROVIDER=claude`, `TTS_PROVIDER=elevenlabs`. No `stub`: check the startup log has **no** "STUB AI PROVIDERS" warning.
- [ ] Provider keys set: `DEEPGRAM_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`.
- [ ] `AUTO_INIT_DB=false` (serverless).
- [x] `CLIENT_IP_HEADER=x-real-ip` (login throttling per real client IP on Vercel). Set in Production on 2026-10-08 (non-sensitive, readable); takes effect on the next production deploy.
- [ ] `SEED_DEMO_USERS` **unset or false** (otherwise known-password demo accounts are created).
- [ ] `API_DOCS` unset (off).
- [ ] `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD` set for first boot. After the admin exists, change the password in the app and consider removing the variable.
- [ ] `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD` per decision B-14.
- [ ] `SESSION_TTL_HOURS`, `LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_MINUTES` per B-13 (defaults 12 h / 5 / 15 min).

## C. Database (before deploy)
- [ ] **Backup:** `pg_dump --format=custom` of the pilot database stored encrypted off the laptop, with the file name and time recorded.
- [ ] **Restore drill done once:** restore into a **scratch** database or Neon branch, run `scripts/init_db.py` there, log in, compare row counts. Never restore into production during this check.
- [ ] **Schema and seed:** `DATABASE_URL=… python scripts/init_db.py` against the pilot database (idempotent; insert-only seed).
- [ ] **Neon point-in-time window:** the configured window is known and recorded.

## D. Pilot setup (after deploy, before inviting users)
- [ ] **Admin login:** works; the admin password has been changed from the bootstrap value.
- [ ] **Teams created:** one per sales lead.
- [ ] **Leads:** created, each with a team.
- [ ] **Managers:** 10–20 created and assigned to teams. Passwords are delivered by the bank's agreed channel.
- [ ] **Bank content roles:** training, product and compliance users created for the bank roles who own content.
- [ ] **KB versions:** only approved KB versions are published (`/queue` shows no unexpected items). The KB list shows "на проверке" only on drafts.
- [ ] **Scenarios:** only pilot-approved scenarios are published; all others stay draft or archived.
- [ ] **C-9:** status recorded.

## E. Smoke test on the deployed build
- [ ] **Health:** `/health` returns `{"status":"ok"}`; responses carry CSP, nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy, X-Request-ID and HSTS.
- [ ] **Six-role walkthrough** with pilot accounts: manager, lead, training, product, compliance, admin (each nav destination opens; no errors in the browser console).
- [ ] **Training run:** one real voice training as a test manager (mic → STT → reply → TTS → finish → result → history → progress), then archive or hide the test data per the agreed procedure.
- [ ] **Throttling:** a wrong password 5× shows the throttle message.
- [ ] **Logs:** Vercel function logs show request ids and no secrets.

## F. Rollback (know before deploy)
- **Code:** promote the previous deployment in Vercel. The schema is additive, so older code works on it.
- **Data:** restore from the backup into a new database or branch, then switch `DATABASE_URL`. Data written after the backup is lost.
- **Disable training without rollback:** unpublish (archive) scenarios, or switch on the Basic Auth gate.

## G. After the pilot starts
- [ ] **Credentials:** delete or secure the local `.env.local` that holds production credentials (A2-11).
- [ ] **Monitoring:** daily and weekly checks from `PILOT_RUNBOOK.md`.
