# Bank pilot decisions

Decisions only Bank Eskhata can make. Engineering has **not** resolved any of them. Each needs a written answer from the bank's accountable role.

## MUST DECIDE BEFORE PILOT
| Id | Decision | Why it blocks a safe launch | Current state |
|---|---|---|---|
| B-3 | **External AI providers** for conversation data: Deepgram (speech → text), ElevenLabs (text → speech), Anthropic (scoring) | Manager speech and transcripts leave the bank (see `PHASE_9_LAUNCH_READINESS.md` §8) | Integrated; not bank-approved |
| B-4 | **DeepSeek specifically** (dialog model), or an approved alternative | It receives the full conversation and scenario profile each turn | Integrated; not bank-approved |
| B-5 | **Provider and data regions** (incl. Neon in US-East) | Data residency | Not decided |
| B-6 | **Hosting model** (current Vercel + Neon SaaS vs private cloud or bank infrastructure) | Where pilot data lives | Running on Vercel + Neon |
| B-9 | **Retention** of transcripts, scores and the audit log; deletion and export | Data is kept indefinitely today | Not decided |
| B-10 / B-11 / B-13 | **Security requirements:** pen test before pilot? IP allow-list or VPN? password policy, session TTL, MFA? | May be mandatory before employees log in | Engineering smoke test only; defaults: 12 h session, 5 failures / 15 min throttle |
| B-14 | **Basic Auth outer gate:** keep during the pilot? | An access-control layer | Set in Production |
| C-9 | **Tax statement** in `merchant_onboarding` objection `obj_taxes` (published KB 1.0.0): confirm, replace or remove | It is live, scoring-relevant product truth flagged by its own note as needing Compliance/Legal confirmation | **Open** |
| C-1…C-6 | **Approved product facts** for РКО, Эквайринг, Зарплатный проект, Кредит; compliance restrictions | Three KBs are developer placeholders, and the fourth carries C-9 | See `PILOT_CONTENT_GATE.md` |
| C-3 | **Эквайринг terminology:** is `merchant_onboarding` the bank's Эквайринг product? | Pilot scope and naming | Unconfirmed |
| C-7 | **Scenario approvals:** which of the 12 scenarios are in the pilot | Only approved scenarios may be published | 1 published (not pilot-approved), 11 drafts |

## MAY BE DECIDED DURING OR AFTER THE CONTROLLED PILOT
Each deferral needs **explicit pilot-owner acceptance**; none is assumed.

| Id | Item | Deferrable because… | Needs acceptance of |
|---|---|---|---|
| B-1 / B-2 | **Four-eyes approval** (author ≠ approver; Product + Compliance) | The current single-step lifecycle with separated role sets works safely for a small content set | Accepting single-approval content for the pilot |
| B-2 | **Dispute review owner**; may compliance open disputed sessions | Disputes are recorded and visible to the lead and admin; they never change scores | Disputes staying informational during the pilot |
| B-7 / B-8 | **SSO / IdP; account provisioning** | Admin-created accounts work for 10–20 users | Manual accounts and password delivery |
| B-12 | **Log export / SIEM** | The audit log is in the app and the database | In-app audit only |
| B-15 | **Historical team membership:** a moved manager's history follows the current team; deactivated managers drop out of team numbers | Small, stable pilot teams | The current behaviour |
| B-16 | **Compliance seeing per-manager score events** in the audit log | Existing journal design (PRD §14) | That visibility, or a request to restrict it |
| C-8 | **Duration hints and success metrics** per scenario | Not needed to run sessions | Their absence |
