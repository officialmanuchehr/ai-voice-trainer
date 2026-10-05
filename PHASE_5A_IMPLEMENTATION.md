# Phase 5A — Manager training experience: implementation record

**Date:** 2026-10-05 · **Base:** security hotfix `7911811` (after Phase 4A `1ee20e4`) · **Scope:** the manager's primary journey only: catalogue → briefing → live session → finish → scoring → result.
**Git:** uncommitted, for review. Nothing pushed, merged or deployed.
**Backend application logic changed: NO** (`git diff -- app/` is empty).

## 1. Manager journey: before → after

| Step | Before (Phase 4A) | After |
|---|---|---|
| Catalogue | Cards with goal, learning goal, topics; "Начать" started a session immediately | Cards: product, title, difficulty, task (3-line clamp), topics, "Выбрать". Loading, empty ("no published trainings") and "nothing matches filters + reset" states. |
| Before starting | None | **Briefing dialog**: product, difficulty, *Ваша задача*, *Чему учит сценарий*, visible client context, a generic description of the level, "Начать тренировку" / "Отмена". One step, no wizard. |
| Session header | Context panel with goal and briefing lines | Page header = scenario title + product · difficulty. **Session bar**: client identity, **timer**, "Завершить тренировку". Task and context in a collapsible panel. |
| Conversation | Messenger-style bubbles | Restrained transcript: "Вы" / client name label, one line per turn, `id="turn-N"` anchors, system notes centred |
| Voice | Mic button with emoji label, "Клиент думает…" text | **Explicit voice-state line** (icon + text, `role="status"`), mic button `aria-pressed`, Space/Enter to talk |
| Finish | Immediate | **Confirmation dialog**, disabled until the first stored turn (the server's existing ≥1 turn rule) with a visible hint |
| Scoring | One "Оцениваю…" line | **Three-step state**: Разговор завершён ✓ → Анализ (spinner, honest wording, no %) → Результат готов. Safe error with "Повторить оценку" / "К списку тренировок". |
| Result | Flat list | Hierarchy: score → cap explanation → takeaway + next skill → critical errors → strengths / improvements → "Вы сказали → Лучше" → claims by verdict → criteria → dispute → version metadata |

## 2. Files changed

| File | Change |
|---|---|
| `static/js/pages/training.js` | Rewritten around explicit states; Phase 3A recovery logic carried over unchanged in substance (`syncChat`, `turnFailed`, `manager_text`, `audio_error`, pending line) |
| `static/index.html` | New catalogue, session, scoring and result markup; briefing and finish dialogs |
| `static/app.js` | Result renderer split into pure `resultHtml()` + `renderResult()`; shared `turnElement()` / `renderTranscript()`; `latencyMeta()` moved here; criterion default weights cached for the override note |
| `static/css/app.css` | Phase 5A component styles (catalogue, briefing, session bar, transcript, voice state, steps, result) |
| `static/session.html` | Transcript container uses the new transcript style (review page shares the renderer) |
| `tests/test_phase5a.py` | New (30 tests) |
| `tests/test_security_html_escaping.py` | Allowlist extended by 4 reviewed attribute expressions: `scoreClass()` ('low'/'high'), two computed numbers, the `VERDICTS` constant map |

## 3. Training catalogue
- **Data:** only the `/scenarios` response (manager-safe, already proven in Phase 2).
- **Card fields read:** `title`, `product_name`, `difficulty`, `goal`, `topics`, `id` (tested: a subset of the API fields).
- **Not invented:** duration, completion, scores, popularity.
- **Difficulty:** the same chip as the design system, a text label plus colour.

## 4. Briefing and start
- **Shows:** product · difficulty, *Ваша задача* (`goal`), *Чему учит сценарий* (`learning_goal`), *Клиент* (the API's `briefing` list), the difficulty explanation.
- **Variant fields:** a briefing value the API marks "варьируется" is shown as "определится при старте".
- **Difficulty text is generic per level** and mirrors how the AI client is instructed in `app/prompts.py` (`DIFFICULTY_RULES`). It's not scenario-specific and adds no client facts.
- **Not shown:** scenario JSON, hidden fields or coaching material.
- **Focus:** opens on "Начать тренировку". Esc, ✕ and Отмена close it.
- **Repeat paths:** history "Повторить" and the after-result "Пройти сценарий ещё раз" also open the briefing; an unavailable scenario gives a safe toast.

## 5. Live session
- **Client identity:** from the session-start response's visible `briefing` only. Name = the "Клиент" entry, subtitle = "Тип бизнеса · Роль собеседника". Without a name it shows **"AI-клиент"**; no attributes are inferred or generated.
- **Context:** the collapsible panel repeats the task, learning goal and visible briefing. It's collapsed by default so the composer stays above the fold.
- **Transcript:** after any failure it's redrawn from `GET /transcript` (Phase 3A). The pending manager line shows "отправляется…" until the server confirms it; turns get `turn-N` IDs so result claims can link to them.

**Voice states** (`#voice-state`, text and icon, never colour alone):

| State | Copy (summary) | Trigger |
|---|---|---|
| `ready` | Готово. Удерживайте кнопку… или напишите реплику | idle |
| `listening` | Идёт запись… Отпустите кнопку | MediaRecorder started (button `aria-pressed=true`) |
| `transcribing` | Распознаю речь и жду ответ клиента… | voice-turn request in flight; one request covers both steps, so the state names both (no timed guess) |
| `thinking` | Клиент думает… | text-turn request in flight |
| `speaking` | Клиент отвечает… | `<audio>` `playing` → `ended` |
| `audio_unavailable` | Озвучка недоступна — ответ показан текстом | `audio_error` from voice-turn, or audio playback error |
| `error` | Реплика не отправлена. Повторите или напишите текстом | `stt_unavailable` / `dialog_unavailable` / network |
| `mic_denied` | Нет доступа к микрофону… продолжайте текстом | `getUserMedia` refused |
| `closed` | Разговор завершён | after finish |

There's no waveform or fake level data.

**Text fallback:** always available. After a failed voice turn, the recognised text is put in the input with "Повторить" (Phase 3A).

## 6. Timer
- **Elapsed `mm:ss`,** counted with `performance.now()` from the moment the browser receives the new session. That's deliberately not the server's `started_at`, so client/server clock skew can't distort it.
- **Display only:** never sent to the server, never ends the session, no effect on scoring (tested statically). It freezes at finish.
- **Not resumed after a reload:** the page has never restored an active session.

## 7. Finish → scoring
- **"Завершить тренировку"** is disabled until at least one turn is stored, matching the server's existing rule; the hint "Завершить можно после первой реплики" is shown.
- **Confirmation dialog** (native `<dialog>`, labelled and described): focus on "Продолжить разговор", Esc cancels.
- **On confirm:** the composer and finish button are hidden, the timer stops, and the scoring panel (`role="status"`, `aria-live`) shows the three steps.
- **Unchanged from before:** polling, the 6-minute client deadline, network retries, and resuming an in-flight scoring job.
- **Failure:** the analysis step turns red, with a safe message and "Повторить оценку". For `scoring_unavailable` the page shows its own text ("…Нажмите «Повторить оценку» — разговор сохранён"), because the server's safe message names the old button label. The server message itself is unchanged.

## 8. Result hierarchy (`resultHtml`, used by the training page and the session review page)

| # | Section | Source (stored data only) |
|---|---|---|
| A | Score `N / 100` + bar (text is the equivalent; bar `aria-hidden`) | `total` |
| A | **Cap explanation**: "Итог ограничен 60 баллами. Без ограничения было бы X. Причина: …", with each trigger and a link to its turn | `cap_reason` |
| B | Main takeaway + "Что тренировать дальше" | `feedback.summary`, `feedback.next_skill` |
| C | "Что нужно исправить в первую очередь": each critical error with quote and explanation, plus one factual sentence on the cap rule | `critical_errors` |
| D/E | "Что получилось" / "Что улучшить" | `feedback.strengths` / `growth_areas` |
| F | "Как сказать лучше": "Вы сказали → Лучше" pairs | `feedback.better_examples` |
| G | "Продуктовые утверждения": grouped **Запрещённые формулировки → Нет в утверждённой базе знаний → Подтверждено базой знаний**, counts, "Реплика N" links, reasons; note naming the KB version checked against | `claim_checks`, `kb_version` |
| — | "Оценка по критериям": name, bar, `score / max`, reason, quote; "(вес в этом сценарии: X вместо Y)" **only** when the scenario overrides the rubric weight | `breakdown`, rubric defaults from `/rubric` |
| H | Actions: "Пройти сценарий ещё раз", "К списку тренировок", dispute (owner only) | existing functionality |
| — | Metadata footer: scenario vN · KB vX · rubric | versions |

- **Missing data:** sections without data are omitted. Claims say "Конкретных утверждений о продукте в разговоре не найдено". Nothing is generated client-side (tested with a minimal payload: no `undefined`, `null` or `NaN`).
- **No invented bands:** the score has no "good/bad" label. Colour follows the existing ≤60 rule, and the number is always the primary signal.

## 9. Compliance and claim presentation
- **Ordering:** claims appear risk-first (forbidden, then unapproved, then approved), each with a text badge, a count, the exact claim, the turn link and the evaluator's reason.
- **Tone:** the language is professional and non-judgemental ("Что нужно исправить в первую очередь"). Critical errors are visible but not dramatic: a red left border, not a full red panel.
- **Audit footer:** the KB version the claims were checked against is stated in the claims section and in the metadata footer.

## 10. Accessibility and responsive behaviour
- **Dialogs:** native `<dialog>` for briefing and finish, labelled (and described for finish); keyboard: Esc closes, focus starts on the safe default.
- **Mic:** usable by keyboard (Space/Enter hold, verified in Chrome); `aria-pressed`; state announced via `role="status"`; never colour alone.
- **Announcements:** scoring steps are a live region; the result panel receives focus when ready; the transcript is `aria-live="polite"`.
- **Buttons:** retry and all actions are real `<button>`s; the score and criterion bars have text equivalents.
- **Narrow screens:** the session bar wraps (client identity on its own line), transcript rows stack (label above text), and claim, compare and criterion rows collapse. Verified at 390 × 844 with no horizontal overflow.

## 11. Tests
- **`tests/test_phase5a.py` (30):**
  - the training page and renderer never reference any of 18 hidden scenario fields;
  - the catalogue and briefing read only fields present in the real `/scenarios` response, and session start only fields in the real `POST /sessions` response;
  - client identity comes only from the visible briefing;
  - only known API routes are called;
  - journey structure (dialogs, timer, live regions, `aria-pressed`, focusable result);
  - Phase 3A recovery intact and scoring failure handled; the timer is display-only;
  - **Node (real `resultHtml`):** cap explanation with turn link; critical errors; claims grouped riskiest-first and escaped; versions and takeaway; weight note only for real overrides; minimal payload invents nothing.
- **Suite:** `pytest` **475 passed** (445 → 475), `pytest tests` 475, Phase 5A first then all reversed 475. Without Node: 36 passed, 7 Node tests skipped.

## 12. Browser verification
**Performed: yes, in real Google Chrome (headless)**, Playwright from the scratchpad virtualenv (not a project dependency).
- **Fake microphone:** Chrome's fake media device, so the real MediaRecorder → voice-turn path ran.
- **Fault injection:** a scratchpad wrapper toggled provider faults on the repo copy (stub providers, demo users).

| Checked | Result |
|---|---|
| Catalogue → briefing (focus on start) → session | Works; client "Шахло · торговая точка… · владелец…" from the visible briefing |
| Timer | 00:00 → 00:02 after 2 s; frozen at finish |
| Finish before first turn | Disabled, hint shown |
| Voice turn (fake mic) | `listening` + `aria-pressed=true` while held → `transcribing` → `ready`; turns `turn-1`, `turn-2` |
| Text turn | Works; finish enabled |
| AI client failure | Voice state `error`, typed text kept, transcript unchanged, safe message + request ID; retry → exactly one new pair |
| TTS failure | `audio_unavailable` + note; conversation continues |
| Finish dialog | Focus on "Продолжить разговор"; Esc keeps the session; confirm → scoring steps → result (focus moved to result) |
| Capped / mis-selling result | "Итог ограничен 60 баллами. Без ограничения было бы 85…"; claim groups; "Реплика 3" link jumps to `#turn-3` |
| Scoring failure → retry | Safe message, step marked error; "Повторить оценку" → result |
| Keyboard | Card → Enter → briefing → Enter starts; Space on mic records |
| Dark mode, 390 × 844 | Rendered; no overflow |
| Every step | **0 CSP violations, 0 JS errors, no hidden scenario value on screen** (6 long hidden strings of the seed scenario watched), no raw provider error |
| Phase 4A all-roles run (updated to the new flow) | 40 page states: 0 CSP violations, 0 overflow |

**Fixed after reviewing screenshots:**
- the briefing note overlapping the difficulty text;
- the cramped session bar at phone width;
- a misleading weight note on every criterion;
- the context panel pushing the composer below the fold;
- the scoring-failure text naming the old button.

**Not verified:**
- a real microphone or speaker (fake device only);
- real ElevenLabs audio playback (stub audio is empty, so `speaking` was not observed live);
- Safari and Edge;
- real-provider latency and real Claude result content.

These remain deployment-gate items 8–9 and 12.

## 13. CSP and hidden data
- **CSP:** unchanged and strict (`script-src 'self'; style-src 'self'`). No inline code; meter widths via CSSOM.
- **Test-harness note:** Playwright's in-page `wait_for_function` uses `eval` and was correctly blocked by the CSP during testing; the script polls from Python instead.
- **Hidden fields:** protection preserved. No API response changed, and the frontend reads no hidden field (tested). The `esc()` hotfix behaviour is unchanged.

## 14. Known limitations
- **No session resume after a page reload:** an active session is left open (unchanged behaviour).
- **The voice-turn state can't distinguish recognition from waiting for the client,** because it's one server request; the state names both.
- **Stub-only verification:** the result's content quality (feedback text, quotes) depends on the real evaluator.
- **No estimated duration in the catalogue:** none exists in the data, and none is invented (A1-11 needs bank values).
- **Transcript links on the review page** work only for turns rendered on the same page, which is always true today.

## 15. Remaining (not started, per scope)
- **Phase 5B:** My Progress / Overview (needs a read-only `/me/progress`).
- **Phases 6–8:** lead, training, product, compliance and admin workspaces; structured editors.
