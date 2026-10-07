# Pilot acceptance matrix

Status: **PASS** (verified with evidence) · **FAIL** · **BLOCKED** (needs a bank decision, content or approval) · **NOT TESTED**. Code existing is not a PASS. Evidence names the test file or the Phase 9 check.

Date: 2026-10-06. Build: Phase 9 working tree on `649a6f5`. Test suite: **730 passed** (Python 3.14 and a clean Python 3.12).

## FUNCTIONAL
| Item | Status | Evidence / notes |
|---|---|---|
| Manager: catalogue → briefing → session → finish → result → history → progress | PASS (stub providers) | Chrome voice journey (`browser_5a`, re-run Phase 9); 5A/5B tests |
| Lead: overview, team, drill-down, recent activity | PASS (stub) | Phase 6 tests; six-role Chrome sweep |
| Content: structured editors, versions, queue | PASS (stub) | Phase 7/8 tests and Chrome reviews |
| Admin: users, teams, audit | PASS | Phase 8 tests and Chrome review |
| Same flows with real providers | NOT TESTED | Real-provider gate G2 |

## SECURITY
| Item | Status | Evidence / notes |
|---|---|---|
| Login throttling | PASS | Phase 3B tests |
| Cookie flags (HttpOnly, SameSite=Lax, Secure on HTTPS) | PASS | `test_security_headers_and_cookie_flags` |
| CSP strict, nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy, request id | PASS | Same test; Chrome: no CSP violations |
| HSTS | PASS (Vercel) | Verified live in Phase 3B; re-check at deploy (checklist E) |
| Safe 4xx/5xx, malformed JSON, oversized bodies | PASS | `test_malformed_requests_get_safe_errors`, 413 tests |
| Input ceilings (A2-2) | PASS | Boundary tests in `test_phase9_acceptance.py` |
| HTML escaping / stored attribute injection | PASS | `test_security_html_escaping.py`, Phase 7/8 Node and Chrome checks |
| `CLIENT_IP_HEADER` set for Vercel | FAIL (config) | Not set in Production; checklist B |
| Preview isolated from production DB | FAIL (config) | `DATABASE_URL` shared Production+Preview; checklist B |
| Bank penetration test | BLOCKED | B-10 (this was an engineering smoke test only) |

## PRIVACY
| Item | Status | Evidence / notes |
|---|---|---|
| Audio never stored | PASS | Code search: no file writes or binary columns, `del` after STT; Phase 9 §7 |
| No secrets committed or in the frontend | PASS | History scan; Phase 9 §5 |
| Logs redact secrets | PASS | Phase 3B redaction tests |
| Transcript access (owner, own-team lead, admin only) | PASS | RBAC matrix |
| Retention policy | BLOCKED | B-9 |
| Provider data processing approval | BLOCKED | B-3, B-4, B-5 |

## CONTENT
| Item | Status | Evidence / notes |
|---|---|---|
| KB review guards (`needs_review`, `draft_note`) block approval and publication | PASS | `test_kb_safety_chain`, Phase 7 tests |
| Published versions immutable | PASS | Phase 7 tests |
| Pilot content approved by the bank | BLOCKED | `PILOT_CONTENT_GATE.md`: 0 of 4 KBs, 0 of 12 scenarios pilot-approved |
| C-9 (`obj_taxes`) resolved | BLOCKED | Compliance/Legal |

## AI PROVIDERS
| Item | Status | Evidence / notes |
|---|---|---|
| Provider failure handling (safe messages, nothing stored on failure, retry) | PASS (simulated) | Phase 3A tests; Chrome scoring-failure retry |
| Persona-break guard (A2-4) | PASS (synthetic outputs) | 12 breaks caught, 10 natural lines untouched |
| Deepgram / DeepSeek / ElevenLabs / Anthropic with real keys | NOT TESTED | Gate G1, needs approval |
| Provider approval | BLOCKED | B-3, B-4 |
| Stub-provider misconfiguration detectable | PASS | Startup warning + test; checklist B |

## VOICE
| Item | Status | Evidence / notes |
|---|---|---|
| Push-to-talk, states, keyboard (fake microphone, Chrome) | PASS | Chrome voice journey |
| Real microphone + real STT/TTS | NOT TESTED | Gate G2 and the device matrix below |
| Microphone denied / no speakers | NOT TESTED (manual) | Device matrix |

## SCORING
| Item | Status | Evidence / notes |
|---|---|---|
| Mis-selling cap (unapproved, forbidden, unknown verdict → 60, `cap_reason`, analytics) | PASS | `test_mis_selling_claim_caps_the_stored_score_everywhere` |
| Deterministic total, fail-closed verdicts, provider validation and retry | PASS | Phase 1b/2/3A tests |
| Real-model scoring quality and latency | NOT TESTED | Gate G1/G2 |

## ANALYTICS
| Item | Status | Evidence / notes |
|---|---|---|
| Version binding in history, progress and lead analytics | PASS | `test_version_binding_end_to_end` |
| Org analytics count managers only | PASS | Phase 8 tests |
| Deactivated or moved managers | PASS (documented behaviour) | B-15 for policy |

## RBAC
| Item | Status | Evidence / notes |
|---|---|---|
| Six-role matrix, 17 read resources + dispute + content writes + session start | PASS | `test_rbac_*`; no unexpected ALLOW |
| Cross-team isolation | PASS | Matrix + Phase 6 tests |

## AUDIT
| Item | Status | Evidence / notes |
|---|---|---|
| Content, user, session, login events with safe details | PASS | Phase 8 tests (no password in audit) |
| Log export / SIEM | BLOCKED (may defer) | B-12 |

## DEPLOYMENT
| Item | Status | Evidence / notes |
|---|---|---|
| CI regression gate | PASS (locally verified) | Workflow added; clean Python 3.12 install gives 730 passed; runs on GitHub after push |
| Idempotent, non-destructive init and seed | PASS (code review + tests) | Phase 9 §6 |
| Production env names present; demo users off; docs off | PASS | Vercel env names (values not read) |
| Provider modes non-stub, `AUTO_INIT_DB=false` (values) | NOT TESTED | Checklist B (operator verifies values) |
| Deploy of the approved build + smoke test | NOT TESTED | Checklist E (deploy not authorised yet) |

## BACKUP / ROLLBACK
| Item | Status | Evidence / notes |
|---|---|---|
| Backup procedure defined | PASS (documented) | Phase 9 §6, checklist C |
| Restore drill | NOT TESTED | No local Postgres tooling; production not touched |
| Code rollback (promote previous deployment) | NOT TESTED | Rehearse at deploy |

## BANK DECISIONS
| Item | Status | Evidence / notes |
|---|---|---|
| Must-decide-before-pilot items | BLOCKED | `BANK_PILOT_DECISIONS.md` |
| Deferrable items | BLOCKED until the pilot owner explicitly accepts the deferral | Same |

## Manual browser and device matrix (to execute; nothing below is claimed)
For each browser:
- login; catalogue; briefing; microphone permission; push-to-talk; STT; AI response; TTS playback;
- finish; scoring; result; repeat; history; progress;
- microphone denied; no audio output; AI provider failure; scoring failure;
- reload during a session; narrow window; keyboard only.

| Browser | Status |
|---|---|
| Chrome desktop (headless, fake mic, stub providers) | PASS for the flows above except real mic/STT/TTS |
| Chrome desktop, real devices + real providers | NOT TESTED |
| Edge desktop | NOT TESTED |
| Safari desktop (only if bank users use it) | NOT TESTED |
