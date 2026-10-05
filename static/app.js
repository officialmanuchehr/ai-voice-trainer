// Shared helpers for every page: API calls, escaping, dates, and the
// score/feedback renderer used by the trainer and session pages.

const DIFFICULTY = { easy: 'Лёгкий', medium: 'Средний', hard: 'Сложный' };
const STATUS = { draft: 'Черновик', approved: 'Утверждено', published: 'Опубликовано', archived: 'Архив' };
const SESSION_STATUS = { active: 'в процессе', scoring: 'оценивается', finished: 'оценено', finish_error: 'ошибка оценки' };

function esc(s) {
  const div = document.createElement('div');
  div.textContent = s == null ? '' : String(s);
  return div.innerHTML;
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
async function criteriaNames() {
  if (!_criteriaNames) {
    _criteriaNames = {};
    for (const r of await api('/rubric')) for (const c of r.criteria) _criteriaNames[c.id] = c.name;
  }
  return _criteriaNames;
}

function scoreClass(total) { return total <= 60 ? 'low' : 'high'; }

// Shown only when the 60-point cap actually lowered the score; lists what triggered it.
function capNote(cap) {
  if (!cap) return '';
  const verdicts = { unapproved: 'нет в базе знаний', forbidden: 'запрещено' };
  const items = cap.triggers.map((t) => t.kind === 'claim'
    ? `<li>Утверждение (${esc(verdicts[t.verdict] || t.verdict)}), реплика ${esc(t.turn_index)}: «${esc(t.claim_text)}»</li>`
    : `<li>Критичная ошибка: ${esc(t.type)}</li>`).join('');
  return `<div class="critical-box">Итог ограничен ${esc(cap.limit)} баллами (без ограничения было бы ${esc(cap.calculated_total)}), потому что:<ul class="plain">${items}</ul></div>`;
}

async function renderResult(el, data, { onDispute } = {}) {
  const names = await criteriaNames();
  const claims = (data.claim_checks || []).map((c) => `
    <div class="claim-row">реплика ${esc(c.turn_index)}: «${esc(c.claim_text)}» —
      <span class="verdict-${esc(c.verdict)}">${esc({ approved: 'подтверждено БЗ', unapproved: 'нет в БЗ', forbidden: 'запрещено' }[c.verdict] || c.verdict)}</span>
      ${c.reason ? ` — ${esc(c.reason)}` : ''}</div>`).join('');
  const breakdown = (data.breakdown || []).map((b) => `
    <div class="criterion">
      <div class="criterion-head"><span>${esc(names[b.criterion_id] || b.criterion_id)}</span>
        <span>${esc(b.score)} / ${esc(b.max)}${b.weight != null && b.weight !== b.max ? ` <span class="muted small">(вес ${esc(b.weight)})</span>` : ''}</span></div>
      ${b.reason ? `<div class="criterion-reason">${esc(b.reason)}</div>` : ''}
      ${b.quote ? `<div class="criterion-quote">«${esc(b.quote)}»</div>` : ''}
    </div>`).join('');
  const critical = (data.critical_errors || []).length
    ? data.critical_errors.map((e) => `<div class="critical-box"><strong>${esc(e.type)}</strong><br/>«${esc(e.quote)}»<br/>${esc(e.explanation)}</div>`).join('')
    : '<p>Критичных ошибок нет.</p>';
  const fb = data.feedback || {};
  const list = (items) => (items || []).length ? `<ul class="plain">${items.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>` : '<p class="muted">—</p>';
  const examples = (fb.better_examples || []).map((e) => `
    <div class="better-example"><div class="was">«${esc(e.was)}»</div><div class="better">«${esc(e.better)}»</div></div>`).join('');

  el.innerHTML = `
    <div class="row"><h2 class="m-0">Результат</h2><span class="spacer"></span>
      <span class="muted small">сценарий v${esc(data.scenario_version)} · база знаний v${esc(data.kb_version)}</span></div>
    <div class="score-total ${scoreClass(data.total)}">${esc(data.total)} / 100</div>
    ${capNote(data.cap_reason)}
    <h3>Резюме</h3><p>${esc(fb.summary)}</p>
    ${fb.next_skill ? `<p><strong>Что тренировать дальше:</strong> ${esc(fb.next_skill)}</p>` : ''}
    <div class="grid"><div><h3>Сильные стороны</h3>${list(fb.strengths)}</div><div><h3>Зоны роста</h3>${list(fb.growth_areas)}</div></div>
    <h3>Как сказать лучше</h3>${examples || '<p class="muted">—</p>'}
    <h3>Продуктовые и комплаенс-ошибки</h3>${critical}
    <h3>Проверка утверждений по базе знаний</h3>${claims || '<p class="muted">Продуктовых утверждений не найдено.</p>'}
    <h3>Баллы по критериям</h3>${breakdown}
    <div id="dispute-area"></div>`;

  const area = el.querySelector('#dispute-area');
  if (data.dispute) {
    area.innerHTML = `<h3>Возражение по оценке</h3><div class="note-box">${esc(data.dispute.comment)}<br/><span class="muted small">отправлено ${fmtDate(data.dispute.at)}</span></div>`;
  } else if (onDispute) {
    area.innerHTML = `<h3>Не согласны с оценкой?</h3>
      <textarea id="dispute-text" placeholder="Опишите, с чем вы не согласны — команда обучения посмотрит"></textarea>
      <div class="row mt-2"><button class="secondary" id="dispute-btn">Отправить возражение</button><span id="dispute-msg" class="small"></span></div>`;
    area.querySelector('#dispute-btn').addEventListener('click', async () => {
      const text = area.querySelector('#dispute-text').value.trim();
      if (!text) return;
      try {
        await onDispute(text);
        area.innerHTML = `<h3>Возражение по оценке</h3><div class="note-box">${esc(text)}<br/><span class="muted small">отправлено</span></div>`;
      } catch (err) {
        area.querySelector('#dispute-msg').textContent = 'Ошибка: ' + err.message;
      }
    });
  }
}

function renderTranscript(el, turns) {
  el.innerHTML = turns.map((t) => `<div class="bubble ${esc(t.role)}">${esc(t.text)}${t.latency_ms != null ? `<span class="meta">ответ ${(t.latency_ms / 1000).toFixed(1)} с</span>` : ''}</div>`).join('')
    || '<p class="muted">Реплик нет.</p>';
}
