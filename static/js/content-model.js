// Content editing model (Phase 7): pure helpers shared by the scenario and
// knowledge-base editors. No DOM here, so the round-trip rules can be tested
// in Node. The backend stays authoritative for validation, lifecycle and
// permissions; these helpers only decide what to show and what to send.

const CONTENT_STATUS_TEXT = { draft: 'Черновик', approved: 'Утверждено', published: 'Опубликовано', archived: 'Архив' };

// KB sections whose entries may carry `needs_review` (mirrors
// app/content.py _REVIEWABLE_KB_SECTIONS) and their editor labels.
const KB_REVIEW_SECTIONS = ['approved_facts', 'approved_arguments', 'objections', 'disclaimers'];
const KB_SECTION_LABELS = {
  approved_facts: 'Утверждённые факты',
  approved_arguments: 'Утверждённые аргументы',
  objections: 'Возражения и утверждённые ответы',
  disclaimers: 'Оговорки',
  forbidden: 'Запрещённые формулировки',
  critical_errors: 'Критичные ошибки',
  draft_note: 'Пометка черновика',
};

function deepClone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

// What blocks approval/publication, for display. The backend computes the
// same list (kb_review_blockers) and alone decides; this only lets the
// editor point at the exact entries before the user tries.
function kbBlockers(data) {
  const blockers = [];
  if (data && data.draft_note) blockers.push({ section: 'draft_note' });
  KB_REVIEW_SECTIONS.forEach((section) => {
    ((data && data[section]) || []).forEach((entry) => {
      if (entry && typeof entry === 'object' && entry.needs_review) blockers.push({ section, id: entry.id });
    });
  });
  return blockers;
}

// Lifecycle buttons a role may see for a version in `status` (mirrors
// app/content.py can_transition). [target, label]
function allowedTransitions(status, perms) {
  return ({
    draft: [['approved', 'Утвердить', perms.approve], ['archived', 'В архив', perms.publish]],
    approved: [['published', 'Опубликовать', perms.publish], ['draft', 'Вернуть в черновик', perms.edit || perms.approve], ['archived', 'В архив', perms.publish]],
    published: [['archived', 'Снять с публикации (в архив)', perms.publish]],
    archived: [],
  }[status] || []).filter((t) => t[2]).map((t) => [t[0], t[1]]);
}

// Suggested next KB version label (the user can change it).
function nextKbVersion(versions) {
  const last = versions.length ? versions[versions.length - 1].version : '1.0.0';
  const parts = String(last).split('.').map((x) => parseInt(x, 10));
  if (parts.length === 3 && parts.every((x) => !Number.isNaN(x))) return `${parts[0]}.${parts[1] + 1}.0`;
  return `${last}-2`;
}

// An unused entry id for a new KB row: `<prefix>_<n>`.
function freshId(entries, prefix) {
  const used = new Set((entries || []).map((e) => e && e.id));
  let n = (entries || []).length + 1;
  while (used.has(`${prefix}_${n}`)) n += 1;
  return `${prefix}_${n}`;
}

// A typed value from an <input>: numbers stay numbers, booleans stay booleans.
function typedValue(original, raw) {
  if (typeof original === 'number') {
    const n = Number(raw);
    return raw === '' || Number.isNaN(n) ? raw : n;
  }
  if (typeof original === 'boolean') return raw === true || raw === 'true';
  return raw;
}

// Client-profile fields as editor rows, in a stable order: known fields in
// catalogue order, then any other keys as stored. A field may have a base
// value, variants, or both.
function profileRows(profile, catalogue) {
  const variants = (profile && profile.variants) || {};
  const keys = [];
  catalogue.forEach((f) => { if (f.id in (profile || {}) || f.id in variants) keys.push(f.id); });
  Object.keys(profile || {}).forEach((k) => { if (k !== 'variants' && !keys.includes(k)) keys.push(k); });
  Object.keys(variants).forEach((k) => { if (!keys.includes(k)) keys.push(k); });
  return keys.map((key) => {
    const known = catalogue.find((f) => f.id === key);
    return {
      key,
      label: known ? known.label : key,
      known: Boolean(known),
      briefing: Boolean(known && known.briefing),
      list: known ? known.list : Array.isArray(profile[key]),
      hasBase: key in (profile || {}),
      hasVariants: key in variants,
    };
  });
}

// Problems the backend would reject (or that would store empty bank text),
// reported before saving. The server still validates everything.
function scenarioProblems(data) {
  const problems = [];
  ['title', 'goal'].forEach((f) => { if (!String(data[f] || '').trim()) problems.push(`Заполните поле «${f === 'title' ? 'Название' : 'Цель разговора'}»`); });
  const variants = (data.client_profile && data.client_profile.variants) || {};
  Object.entries(variants).forEach(([key, options]) => {
    if (!Array.isArray(options) || !options.length) problems.push(`Варианты «${key}»: нужен хотя бы один вариант`);
    else if (options.some((o) => typeof o === 'string' && !o.trim())) problems.push(`Варианты «${key}»: есть пустой вариант`);
  });
  Object.entries(data.client_profile || {}).forEach(([key, value]) => {
    if (Array.isArray(value) && value.some((v) => typeof v === 'string' && !v.trim())) problems.push(`Профиль «${key}»: есть пустой пункт списка`);
  });
  Object.entries((data.config && data.config.criteria_weights) || {}).forEach(([key, w]) => {
    if (!Number.isInteger(w) || w < 0 || w > 100) problems.push(`Вес «${key}» должен быть целым числом 0–100`);
  });
  return problems;
}

function kbProblems(data) {
  const problems = [];
  ['name', 'segment'].forEach((f) => { if (!String(data[f] || '').trim()) problems.push(`Заполните поле «${f === 'name' ? 'Название продукта' : 'Сегмент'}»`); });
  const required = { approved_facts: ['id', 'text'], approved_arguments: ['id', 'text'], objections: ['id', 'trigger', 'approved_response'], disclaimers: ['id', 'text'] };
  Object.entries(required).forEach(([section, fields]) => {
    const ids = new Set();
    (data[section] || []).forEach((entry, i) => {
      fields.forEach((f) => { if (typeof entry[f] !== 'string' || !entry[f].trim()) problems.push(`${KB_SECTION_LABELS[section]}, запись ${i + 1}: заполните «${f}»`); });
      if (ids.has(entry.id)) problems.push(`${KB_SECTION_LABELS[section]}: повторяющийся id ${entry.id}`);
      ids.add(entry.id);
    });
  });
  if (!(data.approved_facts || []).length) problems.push('Нужен хотя бы один утверждённый факт');
  ['forbidden', 'critical_errors'].forEach((section) => {
    if ((data[section] || []).some((s) => !String(s).trim())) problems.push(`${KB_SECTION_LABELS[section]}: есть пустая строка`);
  });
  return problems;
}
