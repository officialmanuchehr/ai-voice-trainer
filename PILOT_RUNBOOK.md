# Pilot runbook — AI voice sales trainer (Bank Eskhata, controlled pilot)

Roles, not people. The bank names who holds each role.

| Role | Holds |
|---|---|
| **Pilot owner** | Go/no-go, scope, accepts deferrals |
| **Platform operator** | Deploy, configuration, backups, logs |
| **Sales leads** | Their team's training |
| **Training team** | Scenarios |
| **Product team** | KB facts |
| **Compliance** | Approval of facts and wording, incident review |
| **Admin** | Accounts and teams |

## Scope
- **Who:** 10–20 client managers in a few teams, each with a sales lead.
- **What:** only the scenarios and KB versions approved in `PILOT_CONTENT_GATE.md`.
- **Status:** training data only. Scores are coaching information, not KPI or HR evaluation.

## Before the pilot starts
1. `DEPLOYMENT_CHECKLIST.md` is complete (sections A–E), and the backup is taken and recorded.
2. Accounts: Admin creates the teams, leads and managers; passwords go through the bank's channel; each user signs in once.
3. **Content freeze:** the approved KB and scenario versions are published. No content edits during the pilot except corrections through the normal version workflow (new draft → approval → publish), announced to the pilot owner.
4. Start-of-pilot check (operator): `/health`, a six-role login, one real test training, no stub-provider warning in the logs.

## What managers do
- Open **Тренировка**, pick a scenario, read the briefing, start, and talk using push-to-talk (or type).
- Finish with **«Завершить и получить оценку»**, read the result, and repeat from **История**.
- **Don't reload or close the tab during a training.** If that happens, the unfinished training stays in History as "в процессе" and can't be continued. Start a new training; nothing is lost.
- If the client voice fails, read the reply on screen. If the client can't reply, re-send the line. If scoring fails, press **«Повторить оценку»**.
- **Use no real customer names or personal data** in conversations. Transcripts are stored and sent to the approved AI providers.
- To disagree with a score, write it under the result and press **«Отправить возражение»**. It's recorded; the score is not changed automatically.

## What leads monitor
- **Обзор** (team activity, average final score, critical errors), **Команда** (per-manager facts, alphabetical), and the manager drill-down.
- Recurring critical errors or claims the KB doesn't confirm are coaching topics, not grounds for HR conclusions.
- Disputes from the team appear on **Обзор** and are discussed with the manager. There is no automatic resolution.

## Who handles what
| Situation | First responder | Then |
|---|---|---|
| Wrong or outdated bank information shown by the AI client or in feedback | Lead or manager reports it to the **Product team** | Product drafts a corrected KB version; **Compliance** approves; Product publishes. If serious, the **pilot owner** may archive the affected scenario until fixed |
| Doubtful compliance wording | **Compliance** | As above; Compliance may mark entries `needs_review` in a new draft |
| AI client fails or answers out of character | Manager retries; lead reports to the **operator** with the time and request code from the message | Operator checks logs (`persona guard replaced…`, provider errors) |
| Scoring fails repeatedly | Manager uses «Повторить оценку»; lead reports | Operator checks provider status and logs |
| Login problems or locked accounts | **Admin** | Throttle releases after 15 min; Admin resets the password if needed |
| Suspected data or security incident | **Operator → pilot owner → bank security** | Disable access (below), preserve logs and the backup |

## Disable or roll back
- **Stop training quickly:** Training or Admin archives the published scenarios (irreversible per version; re-publish a fresh version later), or the operator enables the Basic Auth gate.
- **Code rollback:** promote the previous Vercel deployment.
- **Data rollback:** restore the backup into a new database and switch `DATABASE_URL`. Data after the backup is lost; tell the pilot owner first.

## Routine checks
| When | Who | Check |
|---|---|---|
| **Daily** | Operator | Error and 5xx counts and `persona guard` warnings in the logs; provider errors; the `/queue` content state is unchanged unless announced |
| **Daily** | Leads | Team activity; new disputes |
| **Weekly** | Operator | Backup taken; audit log review of content and user changes (Admin/Compliance) |
| **Weekly** | Pilot owner | Metrics below; open issues; content corrections |

## Pilot metrics to collect
- **Activity:** managers who trained, sessions started and scored per week, completion rate (from Обзор).
- **Results:** score trend and per-criterion averages (team and individual, coaching use only).
- **Risk:** critical errors and unapproved or forbidden claims, by type.
- **Reliability:** dialog response latency (stored per turn), provider failures, scoring failures and retries.
- **Feedback:** disputes and their outcome (recorded manually by the lead or training team).
- **Quality:** wrong-information reports and how fast they were fixed; manager and lead feedback (bank survey).
