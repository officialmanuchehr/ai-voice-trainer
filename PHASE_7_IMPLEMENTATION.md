# Phase 7 — Scenario and knowledge-base content management

**Date:** 2026-10-06 · **Base:** `1b91fb6` (Phase 6) · **Status:** implemented, **uncommitted**, not pushed or deployed.

## Scope
Structured editors replace the raw-JSON dialogs for scenarios and the knowledge base (KB). They sit on top of the **existing** content model, API, lifecycle and permissions.

Unchanged:
- statuses and lifecycle; `can_transition`;
- the role sets; no four-eyes rule;
- schema; scoring;
- `needs_review` and `draft_note` guards;
- version binding.

## C-9 — unresolved tax statement in the published merchant KB (bank content blocker)
- **Finding:** KB `merchant_onboarding` **1.0.0 (published)** contains objection `obj_taxes`. Its `approved_response` makes a tax statement ("переводы между физлицами налогом не облагаются…"). The entry's own `compliance_note` says it must be confirmed by Compliance/Legal **before publication**, and nothing records that confirmation. The entry has no `needs_review`, so the review guard treats the KB as clean, and the claim checker treats the response as authorised language.
- **Decision:**
  - no new marker or policy;
  - not every `compliance_note` is a blocker;
  - 1.0.0 stays immutable, and sessions bound to it stay bound;
  - the correction goes through the normal version workflow: published 1.0.0 → new draft → `needs_review: true` on `obj_taxes` → Compliance/Legal resolves the wording → approve → publish.
- **Engineering does not decide the wording:** no confirmation, rewrite or deletion of the statement; no tax-law inference; no generated text.
- **Status:**
  - Phase 7 implementation is **not** blocked;
  - Bank Eskhata product content can **not** be declared fully pilot-ready until Compliance/Legal resolves C-9;
  - recorded in `PILOT_READINESS_PLAN.md` (C-9);
  - covered by tests (synthetic replica and a read-only check of the real KB) and by the browser review (corrective draft blocked on `obj_taxes` while 1.0.0 stayed byte-identical).

## Content schema inventory (from the backend, not the UI)
**Scenario** (`ScenarioVersion.data`, normalised by `validate_scenario_content`):

| Field | Kind | Audience |
|---|---|---|
| `title` | text (required) | visible to managers |
| `product_id` | enum: existing products | visible to managers |
| `difficulty` | enum: `easy`, `medium`, `hard` | visible to managers |
| `rubric_id` | enum: rubrics | internal |
| `topics` | enum list (`TOPICS`) | visible to managers |
| `goal` | text (required) | visible to managers |
| `config.learning_goal` | text | visible to managers (briefing) |
| `config.criteria_weights` | {criterion: int 0–100} | internal |
| `config.good_examples`, `config.feedback_hints` | string lists | internal (evaluator) |
| `client_profile` | stored **verbatim** | see below |

`client_profile` is free-form, but the AI client reads 21 known keys (`app/prompts.py`).
- **Briefing (shown to managers):** 8 keys from `BRIEFING_FIELDS`.
- **Hidden from managers:** all other keys.
- **Lists:** `objections`, `decision_criteria`, `current_products`.
- **`variants`:** maps a field to a list of options. A field may have **both** a base value and variants (seed `business_type`).
- **Unknown keys:** stored and passed back unchanged.

**KB** (`KnowledgeBase.data`, stored as sent by `validate_kb_content`):
- `id`, `name`, `segment`, optional `draft_note`;
- `approved_facts`: `id`, `text` (required), `type` (seed values: process, feature, condition, tariff, benefit; free text in the backend), `value` (a structured object on one seed fact: `{limit, currency, period, commission_pct}` with numbers), `needs_review`;
- `approved_arguments`: `id`, `text`;
- `objections`: `id`, `trigger`, `approved_response`, `compliance_owned`, `compliance_note`;
- `disclaimers`: `id`, `text`, `compliance_owned`;
- `forbidden`, `critical_errors` (string lists);
- extra top-level keys `exercise_type`, `rubric_id` and `goal`;
- any unknown keys.

## Role and action matrix (backend; the UI only shows what this allows)
| Action | Scenario | KB |
|---|---|---|
| Create / edit draft | training, admin | product, compliance, admin |
| Approve | product, compliance, admin | compliance, admin (refused while any `needs_review` or `draft_note` remains) |
| Approved → draft | edit + approve roles | edit + approve roles |
| Publish | training, admin (needs a clean published KB) | product, admin (same guard) |
| Archive (irreversible) | training, admin | product, admin |

Bank decisions B-1/B-2 note that one compliance user can edit and approve the same KB.

## Editors
- **Shared design (`content-editor.js`, `FormBinder`):** the form is rendered from a deep copy of the stored version, and every control is bound to exactly one value. An edit changes that value only; everything else is sent back as loaded. There are no client-side transformations: no trimming, re-ordering or type coercion.
- **Scenario editor (`scenario-editor.js`):**
  - **Basics:** title, product (shows whether that product has a published, clean KB), difficulty, rubric, topics.
  - **Visible to the manager:** goal, learning goal, the briefing profile fields.
  - **Hidden from the manager — AI-client profile:** all other fields, each labelled "видит менеджер" or "скрыто от менеджера".
  - **Training and scoring (internal):** weight overrides, examples, hints.
  - **Profile fields:** base value and variants are edited **independently**; list fields are repeatable rows; unknown or non-string values are shown read-only; unknown keys are marked "не используется AI-клиентом".
  - **Also on the page:** version history and a read-only JSON view.
- **KB editor (`kb-editor.js`):**
  - **Blocker panel:** follows the working copy and lists every `needs_review` entry in every section, plus `draft_note`, each linked to its entry.
  - **Product:** name and segment, plus extra top-level fields shown read-only.
  - **Entry sections:** facts, arguments, objections, disclaimers. Each entry has:
    - id and text (or trigger and response);
    - **"Требует проверки — блокирует утверждение и публикацию"** (`needs_review`);
    - **"Формулировка за комплаенсом"** (`compliance_owned`);
    - **"Комментарий комплаенса (справочно, сам по себе не блокирует)"** (`compliance_note`);
    - a typed editor for structured `value` fields: numbers stay numbers, the field set is fixed, and invalid numbers are held back and reported;
    - other keys shown read-only.
  - **Forbidden formulations and critical errors:** repeatable rows.
  - **Version comment.**
  - **Version history:** status, review count, author, approver, publication date, notes.
  - **Read-only JSON view.**
- **`draft_note`:** shown prominently with an explanation, removed only through **"Снять пометку черновика…"** and a confirmation, and never cleared on save.
- **New KB version:** a dialog (version number suggested, editable). It copies the base version **with all flags**, and the base is unchanged.
- **New product:** id, version, name, segment and the first fact typed by the user. **Nothing is prefilled:** the old template's fact, `rubric_id` and `goal` are gone.
- **Raw JSON:** no editable raw JSON remains. A read-only "Технический вид" is kept for transparency. Structured forms round-trip all audited content, so no editable fallback is needed.

## Versioning and overwrite protection
- **Banner:** always states what a save does. For example: "Черновик v2 — изменения сохраняются в эту версию", or "Новая версия на основе v1 — v1 (Опубликовано) не изменится; при сохранении появится черновик v2".
- **Small backend fix:** `PUT /admin/scenarios/{id}` accepts an optional `base_version`. If a newer draft exists, the edit is refused with **409** instead of replacing that draft. Clients that don't send it keep the old behaviour.
- **In the UI:** viewing v1 while draft v2 exists offers "Открыть черновик v2" instead of "Создать новую версию".
- **History tables:** mark the live version ("действующая") and the open one.

## Approval, publish and blocked transitions
- **Confirmation dialogs:** every transition opens an accessible `<dialog>` (focus on Отмена; Escape cancels; focus returns) naming the content type, the product or scenario, the version and the current → target status. Effects are described without exaggeration:
  - **Scenario publish:** available to managers for new sessions; the previous published version is archived.
  - **KB publish:** becomes the product's active KB for new sessions (AI client and evaluator).
  - **Archive:** irreversible. Archiving the published KB means no new sessions can start for that product.
  - **In every case:** past sessions stay bound to their versions.
- **Refusals:** `kb_unreviewed`, `kb_not_clean`, lifecycle and permission refusals show the server message and the exact `unreviewed` items as returned. Nothing is presented as a warning that can be ignored.
- **Unsaved edits:** while edits are unsaved, transitions are refused with "сохраните изменения".

## Validation
- **Server:** remains authoritative.
- **Before saving, the frontend reports:**
  - required text;
  - empty list rows or variants (the server would store empty KB strings);
  - duplicate entry ids;
  - weights that aren't integers 0–100;
  - numbers mistyped in structured values.
- **Seed content** passes these checks unchanged (tested).

## Unsaved changes
- **Leaving the page:** a dirty indicator, a `beforeunload` warning, and a confirmation when leaving the editor ("← Все …", opening another version).
- **No autosave:** saving is always explicit.

## Audit
Unchanged. The editors use the existing audited routes: `scenario.create`, `scenario.edit_draft`, `scenario.new_version`, `scenario.status`, `kb.new_version`, `kb.edit_draft`, `kb.status`.

## Backend changes (small, no schema)
1. Optional `base_version` overwrite guard on scenario edits.
2. `PUT /admin/kb/...` keeps the existing `notes` when the field is omitted.
3. `/admin/meta` adds `profile_fields`, generated from `prompts.profile_field_labels()`, `PROFILE_LIST_FIELDS` and `BRIEFING_FIELDS`.
4. `/admin/kb` adds `review_blockers` (a count) per version, using `kb_review_blockers`.

## Security
- **Escaping:** every stored value goes through `esc()` (inputs, textareas, options, read-only fields). No new `KNOWN_SAFE` entries.
- **Malicious input:** tested in Node and in the browser (quotes, `<img onerror>`, `</textarea><script>`); nothing executed and no elements were injected.
- **CSP:** unchanged and strict; no native `prompt`, `confirm` or `alert`.
- **Manager APIs:** unchanged; hidden fields of structured content stay out of the catalogue and the session start (tested).

## Accessibility and responsive
- **Forms:** every control has a label (checked in the browser). Lists are `fieldset` plus `legend`; badges carry text.
- **Keyboard:** checkboxes and buttons work from the keyboard, and a newly added row receives focus.
- **Narrow screens:** tables become cards below 640px, with no overflow at 390px in light or dark mode.

## Tests
- **`tests/test_phase7_content.py` (41):**
  - scenario round trip for **all 12 seed scenarios**; base value plus variants, list fields and an unknown key survive;
  - the overwrite guard and legacy behaviour; hidden fields still hidden from managers; the meta catalogue;
  - KB round trip for **all 4 seed KBs**, including `value` numbers, compliance fields and extra keys;
  - notes kept or changed; blocker counts; the real merchant C-9 state (read-only);
  - the synthetic C-9 corrective flow: 1.0.0 immutable, the session stays bound, blocked while flagged, the flag survives other saves, explicit resolution, then approve and publish, with old 1.0.0 archived and its content unchanged;
  - edit and transition permissions per role, server-side; published KB immutable; scenario publishing still requires a clean published KB.
- **`tests/test_phase7_frontend.py` (15):**
  - module order; no editable JSON or native dialogs; no prefilled product content;
  - frontend lifecycle and review sections mirror the backend;
  - blocker vs guidance labels; visible, hidden and internal sections; confirmations;
  - in Node: display blockers equal backend blockers for every seed KB; seed passes the frontend checks; profile rows; typed values; a binder edit changes exactly one path; malicious content escaped.
- **Updated:**
  - `test_phase4a.py`: shared modules;
  - `test_security_html_escaping.py`: sink checks now point at the editor modules, since the old admin dialogs are gone.
- **Results:** **626 passed** (baseline 570), and 626 in reverse file order. Without Node, the static checks pass and the Node checks are skipped.

## Browser verification (Chrome headless, stub data, scratchpad only)
35 checks passed. No XSS, injected elements, CSP violations, native dialogs, JS errors, "undefined" or "NaN", unlabelled controls or overflow.

**Scenario workflow:**
- published v1 is read-only, with visible, hidden and internal sections and base plus variants together;
- "new version based on v1" with its banner; the dirty indicator and leave guard;
- save to draft v2 (v1 unchanged; v2 equals v1 except the edited field);
- v1 then offers only "Открыть черновик v2";
- a new scenario with malicious title, goal and profile values; the editor warned when the product had no published KB;
- product approves (confirmation names the version and target) and the trainer publishes (confirmation explains the effect);
- the manager catalogue shows the malicious title inert.

**KB workflow:**
- the list shows "на проверке: 6" for RKO; the RKO draft lists all 6 blockers including `draft_note`; product sees no approve button;
- a new synthetic product with no prefilled fact and a flagged fact;
- compliance's approve is refused, listing `fact_1`; unchecking the flag updates the panel; saving keeps the notes; approve, then publish (confirmation explains source of truth); published read-only.

**C-9:**
- merchant 1.0.0 shows `obj_taxes` with "за комплаенсом" and "есть комментарий комплаенса" and no false blocker;
- corrective draft 1.1.0 with `needs_review` on `obj_taxes` lists it as a blocker, and compliance approval is refused;
- 1.0.0 stayed byte-identical.

**Roles, layout and keyboard:**
- training has a read-only KB and can't create products; admin sees edit and approve;
- dark mode and 390px for both editors;
- keyboard: checkbox toggling, focus moving to a new row, the confirm dialog focusing "Отмена", Escape keeping the editor.

**Fixed during the review:** topic checkboxes were misaligned (CSS).

## Bank-dependent decisions affecting content
- **C-9:** resolve `obj_taxes`.
- **C-1…C-8:** product facts, Эквайринг terminology (`merchant_onboarding` shown as configured), compliance restrictions, approval of the 11 draft scenarios.
- **B-1/B-2:** four-eyes rule and who approves what.
- **Not touched here:** providers, hosting, retention, SSO.

## Known limitations
- No diff against the live version (plan §7 lists one; out of scope for Phase 7).
- No approvals queue or archive-impact listing of dependent scenarios (A1-6, Phase 8).
- Fact `type` is free text with the used values as a hint; the backend has no enum.
- The structured `value` field set can't be extended in the editor; values can be edited.
- Unknown profile keys and non-string values can be viewed and removed, not edited.
- The catalogue preview shows a base value even when variants exist (existing briefing behaviour). Sessions use the drawn variant.
- An archived version can't be restored (existing lifecycle). Confirmations say so.
- Active-session resume is unchanged (5B limitation).
