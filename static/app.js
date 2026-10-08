// Shared helpers for every page: API calls, escaping, dates, and the
// score/feedback renderer used by the trainer and session pages.

const DIFFICULTY = { easy: 'Лёгкий', medium: 'Средний', hard: 'Сложный' };
const STATUS = { draft: 'Черновик', approved: 'Утверждено', published: 'Опубликовано', archived: 'Архив' };
const SESSION_STATUS = { active: 'в процессе', scoring: 'оценивается', finished: 'оценено', finish_error: 'ошибка оценки' };

// HTML-escapes a value for element content AND quoted attribute values
// (title="…", value="…", data-*="…"). Pure string replacement, no DOM: every
// character is replaced in one pass, so the entities it produces are never
// re-escaped. Quotes must be escaped — the previous DOM-based version
// (textContent → innerHTML) left " and ' raw, which let stored text break out
// of an attribute. CSP is defence in depth, not the escaping boundary.
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function esc(s) {
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (ch) => HTML_ESCAPES[ch]);
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// Every failure mode (network drop, proxy error page, 4xx/5xx JSON) surfaces
// as a thrown Error with a readable message. 401 sends the user to /login.
async function api(url, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (opts.json !== undefined) {
    opts.body = JSON.stringify(opts.json);
    opts.headers['Content-Type'] = 'application/json';
    delete opts.json;
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch (err) {
    throw Object.assign(new Error('Нет связи с сервером. Проверьте сеть и попробуйте ещё раз.'), { code: 'network' });
  }
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (res.status === 401 && !url.startsWith('/auth/login')) {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
    throw new Error('требуется вход');
  }
  if (!res.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join('; ');
    // Unexpected server failures carry no safe detail; never show raw HTTP text.
    if (!detail) detail = res.status >= 500 ? 'Сервис временно недоступен. Попробуйте ещё раз.' : `Ошибка запроса (${res.status})`;
    // Server errors carry a request id that support can find in the server log.
    if (res.status >= 500 && data && data.request_id) detail += ` (код запроса: ${data.request_id})`;
    // `code` and the rest of the body (e.g. manager_text) let pages recover.
    throw Object.assign(new Error(detail), { status: res.status, code: data && data.code, data });
  }
  return data;
}

// initPage() (auth guard + app shell) lives in /static/js/shell.js.

let _criteriaNames = null;
let _criteriaWeights = null;
async function criteriaNames() {
  if (!_criteriaNames) {
    _criteriaNames = {};
    _criteriaWeights = {};
    for (const r of await api('/rubric')) for (const c of r.criteria) { _criteriaNames[c.id] = c.name; _criteriaWeights[c.id] = c.weight; }
  }
  return _criteriaNames;
}

function scoreClass(total) { return total <= 60 ? 'low' : 'high'; }

const VERDICTS = {
  forbidden: { label: 'Запрещённые формулировки', badge: 'error' },
  unapproved: { label: 'Нет в утверждённой базе знаний', badge: 'warning' },
  approved: { label: 'Подтверждено базой знаний', badge: 'success' },
};

// Link to a transcript line rendered on the same page (#turn-N), if known.
function turnRef(index) {
  return index ? `<a href="#turn-${encodeURIComponent(index)}">Реплика ${esc(index)}</a>` : '<span class="muted">—</span>';
}

// The whole result as an HTML string — pure (no DOM), built only from the
// stored score payload; every value goes through esc(). Sections without
// data are omitted or say so; nothing is generated client-side.
// defaults: the rubric's own criterion weights, so a scenario override can be
// pointed out (and only then).
function resultHtml(data, names = {}, defaults = {}) {
  const fb = data.feedback || {};
  const total = data.total;
  const cap = data.cap_reason;
  const critical = data.critical_errors || [];
  const claims = data.claim_checks || [];
  const strengths = fb.strengths || [];
  const growth = fb.growth_areas || [];
  const examples = fb.better_examples || [];
  const list = (items) => `<ul class="feedback-list">${items.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>`;

  const capBlock = cap ? `
    <div class="alert error mt-3" role="note">
      <strong>Итог ограничен ${esc(cap.limit)} баллами.</strong>
      Без ограничения было бы ${esc(cap.calculated_total)}. Причина:
      <ul class="feedback-list">${cap.triggers.map((t) => t.kind === 'claim'
        ? `<li>${esc(VERDICTS[t.verdict]?.label || t.verdict)} — ${turnRef(t.turn_index)}: «${esc(t.claim_text)}»</li>`
        : `<li>Критичная ошибка: ${esc(t.type)}</li>`).join('')}</ul>
    </div>` : '';

  const hero = `
    <div class="result-hero">
      <div class="score-block">
        <div class="score-value ${scoreClass(total)}">${esc(total)}<small> / 100</small></div>
        <div class="meter" aria-hidden="true"><span class="meter-fill ${scoreClass(total)}" data-pct="${Number(total) || 0}"></span></div>
      </div>
      <div>
        ${fb.summary ? `<p class="takeaway">${esc(fb.summary)}</p>` : ''}
        ${fb.next_skill ? `<p class="next-skill m-0"><span class="muted">Что тренировать дальше:</span> <span class="badge info plain">${esc(fb.next_skill)}</span></p>` : ''}
      </div>
    </div>
    ${capBlock}`;

  const criticalBlock = critical.length ? `
    <section class="result-section" aria-labelledby="res-critical">
      <h3 id="res-critical">Что нужно исправить в первую очередь</h3>
      <p class="section-note">Критичные ошибки ограничивают итог ${esc(cap ? cap.limit : 60)} баллами независимо от остальных критериев.</p>
      ${critical.map((e) => `<div class="issue">
        <div class="issue-title">${esc(e.type)}</div>
        ${e.quote ? `<div class="issue-quote">«${esc(e.quote)}»</div>` : ''}
        ${e.explanation ? `<div class="issue-text">${esc(e.explanation)}</div>` : ''}
      </div>`).join('')}
    </section>` : '';

  const feedbackBlock = (strengths.length || growth.length) ? `
    <section class="result-section grid">
      <div><h3>Что получилось</h3>${strengths.length ? list(strengths) : '<p class="muted">Оценщик не выделил сильных сторон.</p>'}</div>
      <div><h3>Что улучшить</h3>${growth.length ? list(growth) : '<p class="muted">Оценщик не выделил зон роста.</p>'}</div>
    </section>` : '';

  const examplesBlock = examples.length ? `
    <section class="result-section" aria-labelledby="res-better">
      <h3 id="res-better">Как сказать лучше</h3>
      ${examples.map((e) => `<div class="compare">
        <div class="was"><span class="compare-label">Вы сказали</span>«${esc(e.was)}»</div>
        <div class="better"><span class="compare-label">Лучше</span>«${esc(e.better)}»</div>
      </div>`).join('')}
    </section>` : '';

  const groups = ['forbidden', 'unapproved', 'approved']
    .map((verdict) => ({ verdict, items: claims.filter((c) => c.verdict === verdict) }))
    .filter((g) => g.items.length);
  const claimsBlock = `
    <section class="result-section" aria-labelledby="res-claims">
      <h3 id="res-claims">Продуктовые утверждения</h3>
      <p class="section-note">Каждое утверждение о продукте сверено с утверждённой базой знаний (версия ${esc(data.kb_version)}).</p>
      ${groups.length ? groups.map((g) => `<div class="claim-group">
        <h4><span class="badge ${VERDICTS[g.verdict].badge}">${esc(VERDICTS[g.verdict].label)}</span><span class="muted">${g.items.length}</span></h4>
        ${g.items.map((c) => `<div class="claim"><div>${turnRef(c.turn_index)}</div>
          <div>«${esc(c.claim_text)}»${c.reason ? `<div class="claim-reason">${esc(c.reason)}</div>` : ''}</div></div>`).join('')}
      </div>`).join('') : '<p class="muted">Конкретных утверждений о продукте в разговоре не найдено.</p>'}
    </section>`;

  const criteria = (data.breakdown || []).map((b) => {
    const pct = b.max ? Math.max(0, Math.min(100, (b.score / b.max) * 100)) : 0;
    const overridden = b.weight != null && defaults[b.criterion_id] != null && b.weight !== defaults[b.criterion_id];
    return `<div class="criterion-row">
      <div class="criterion-name">${esc(names[b.criterion_id] || b.criterion_id)}</div>
      <div class="meter" aria-hidden="true"><span class="meter-fill" data-pct="${pct}"></span></div>
      <div class="criterion-score">${esc(b.score)} / ${esc(b.max)}</div>
      ${(b.reason || b.quote || overridden) ? `<div class="criterion-detail">
        ${b.reason ? esc(b.reason) : ''}
        ${overridden ? ` <span class="muted">(вес в этом сценарии: ${esc(b.weight)} вместо ${esc(defaults[b.criterion_id])})</span>` : ''}
        ${b.quote ? `<div class="criterion-quote">«${esc(b.quote)}»</div>` : ''}
      </div>` : ''}
    </div>`;
  }).join('');
  const criteriaBlock = criteria ? `
    <section class="result-section" aria-labelledby="res-criteria">
      <h3 id="res-criteria">Оценка по критериям</h3>
      <div class="criteria">${criteria}</div>
    </section>` : '';

  return `
    <h2 class="sr-only">Результат тренировки</h2>
    ${hero}${criticalBlock}${feedbackBlock}${examplesBlock}${claimsBlock}${criteriaBlock}
    <div id="dispute-area" class="result-section"></div>
    <p class="result-meta">Сценарий v${esc(data.scenario_version)} · база знаний v${esc(data.kb_version)}${data.rubric_id ? ` · рубрика ${esc(data.rubric_id)}` : ''}</p>`;
}

async function renderResult(el, data, { onDispute } = {}) {
  const names = await criteriaNames();
  el.innerHTML = resultHtml(data, names, _criteriaWeights);
  // Bar widths via CSSOM (allowed by the CSP), not inline style attributes.
  el.querySelectorAll('.meter-fill[data-pct]').forEach((fill) => { fill.style.width = fill.dataset.pct + '%'; });

  const area = el.querySelector('#dispute-area');
  if (data.dispute) {
    area.innerHTML = `<h3>Возражение по оценке</h3><div class="note-box">${esc(data.dispute.comment)}<br/><span class="muted small">отправлено ${fmtDate(data.dispute.at)}</span></div>`;
  } else if (onDispute) {
    area.innerHTML = `<h3>Не согласны с оценкой?</h3>
      <label class="sr-only" for="dispute-text">Ваше возражение</label>
      <textarea id="dispute-text" maxlength="2000" placeholder="Опишите, с чем вы не согласны — команда обучения посмотрит"></textarea>
      <div class="row mt-2"><button type="button" class="secondary" id="dispute-btn">Отправить возражение</button><span id="dispute-msg" class="small" role="status"></span></div>`;
    area.querySelector('#dispute-btn').addEventListener('click', async (e) => {
      const text = area.querySelector('#dispute-text').value.trim();
      if (!text) return;
      setLoading(e.currentTarget, true);
      try {
        await onDispute(text);
        area.innerHTML = `<h3>Возражение по оценке</h3><div class="note-box">${esc(text)}<br/><span class="muted small">отправлено</span></div>`;
      } catch (err) {
        setLoading(e.currentTarget, false);
        area.querySelector('#dispute-msg').textContent = 'Ошибка: ' + err.message;
      }
    });
  } else {
    area.remove();
  }
}

// One transcript line as a DOM element (text via textContent — never HTML).
// id="turn-N" lets result sections link to the line a claim came from.
function turnElement(role, text, { meta, clientName, turnIndex, pending } = {}) {
  const row = document.createElement('div');
  row.className = `turn turn-${role === 'manager' || role === 'ai_client' ? role : 'system'}${pending ? ' turn-pending' : ''}`;
  if (turnIndex) row.id = 'turn-' + turnIndex;
  if (role === 'manager' || role === 'ai_client') {
    const who = document.createElement('div');
    who.className = 'turn-who';
    who.textContent = role === 'manager' ? 'Вы' : (clientName || 'Клиент');
    row.appendChild(who);
  }
  const body = document.createElement('div');
  body.className = 'turn-text';
  body.textContent = text;
  if (meta) {
    const m = document.createElement('span');
    m.className = 'meta';
    m.textContent = meta;
    body.appendChild(m);
  }
  row.appendChild(body);
  return row;
}

function latencyMeta(ms) {
  return ms != null ? `ответ ${(ms / 1000).toFixed(1)} с` : null;
}

function renderTranscript(el, turns, clientName) {
  el.innerHTML = '';
  if (!turns.length) {
    el.innerHTML = '<p class="transcript-empty">Реплик нет.</p>';
    return;
  }
  for (const t of turns) el.appendChild(turnElement(t.role, t.text, { meta: latencyMeta(t.latency_ms), clientName, turnIndex: t.turn_index }));
}
