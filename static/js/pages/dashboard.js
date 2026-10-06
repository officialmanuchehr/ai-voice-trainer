// Dashboard: KPIs, weekly trend, team skills, products, critical errors and
// claims, recent team activity (named views only) and disputes — all from
// /dashboard/data. Facts only: no thresholds, flags or classifications.

const $ = (id) => document.getElementById(id);
const tooltip = $('tooltip');
let me = null;

function showTip(e, html) {
  tooltip.innerHTML = html;
  tooltip.style.display = 'block';
  const x = Math.min(e.clientX + 14, window.innerWidth - tooltip.offsetWidth - 8);
  tooltip.style.left = x + 'px';
  tooltip.style.top = (e.clientY + 14) + 'px';
}
function hideTip() { tooltip.style.display = 'none'; }

function kpi(label, value, sub) {
  return `<div class="kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value ?? '—')}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ''}</div>`;
}

function renderKpis(k) {
  const scoredSub = k.sessions_started ? `начато ${k.sessions_started}` : '';
  const critical = kpi('Тренировки с критичными ошибками', k.sessions_scored ? k.sessions_with_critical_errors : null, k.sessions_scored ? `из ${k.sessions_scored} оценённых · ошибок ${k.critical_errors}` : '');
  // Sales leads get a short coaching view; other roles keep the operational KPIs.
  $('kpis').innerHTML = (me.role === 'sales_lead' ? [
    kpi('Менеджеры с оценёнными тренировками', k.managers_trained, k.total_managers ? `из ${k.total_managers} в команде` : ''),
    kpi('Оценённых тренировок', k.sessions_scored, scoredSub),
    kpi('Средний итоговый балл', k.avg_score, 'из 100'),
    critical,
  ] : [
    kpi('Тренировок', k.sessions_started, `оценено ${k.sessions_scored}${k.completion_rate != null ? ` · завершено ${k.completion_rate}%` : ''}`),
    kpi('Средний итоговый балл', k.avg_score, 'из 100'),
    kpi('Менеджеры с тренировками', k.active_managers, k.total_managers ? `из ${k.total_managers}` : ''),
    critical,
    kpi('Время ответа AI-клиента', k.avg_latency_ms != null ? (k.avg_latency_ms / 1000).toFixed(1) + ' с' : null, 'цель — до 2–4 с'),
    kpi('Оспорено оценок', k.dispute_rate != null ? k.dispute_rate + '%' : null, 'от оценённых'),
  ]).join('');
}

// Single-series line: average final score per calendar week (no reference line —
// there is no bank-approved target).
function renderTrend(trend) {
  const points = trend.filter((t) => t.avg_score != null);
  $('trend-table').innerHTML = `<tr><th>Неделя с</th><th class="num">Тренировок</th><th class="num">Средний балл</th></tr>` +
    trend.map((t) => `<tr><td>${esc(t.week_start)}</td><td class="num">${t.sessions}</td><td class="num">${t.avg_score ?? '—'}</td></tr>`).join('');
  if (!points.length) { $('trend').innerHTML = '<p class="muted">Нет оценённых тренировок за период.</p>'; return; }
  const W = 520, H = 220, L = 34, R = 12, T = 12, B = 28;
  const x = (i) => points.length === 1 ? L + (W - L - R) / 2 : L + i * (W - L - R) / (points.length - 1);
  const y = (v) => T + (100 - v) * (H - T - B) / 100;
  const grid = [0, 20, 40, 60, 80, 100].map((v) => `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis-text" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join('');
  const labelEvery = Math.ceil(points.length / 6);
  const xLabels = points.map((p, i) => i % labelEvery === 0 ? `<text class="axis-text" x="${x(i)}" y="${H - 8}" text-anchor="middle">${p.week_start.slice(5).split('-').reverse().join('.')}</text>` : '').join('');
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.avg_score)}`).join(' ');
  const dots = points.map((p, i) => `<circle class="dot" cx="${x(i)}" cy="${y(p.avg_score)}" r="4"/>`).join('');
  const hits = points.map((p, i) => `<rect data-i="${i}" x="${x(i) - 18}" y="${T}" width="36" height="${H - T - B}" fill="transparent"/>`).join('');
  $('trend').innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Средний балл по неделям">
    ${grid}${xLabels}<path class="line" d="${path}"/>${dots}${hits}</svg>`;
  $('trend').querySelectorAll('rect[data-i]').forEach((r) => {
    const p = points[+r.dataset.i];
    r.addEventListener('mousemove', (e) => showTip(e, `Неделя с ${esc(p.week_start)}<br/>Средний балл: <b>${p.avg_score}</b><br/>Тренировок: ${p.sessions}`));
    r.addEventListener('mouseleave', hideTip);
  });
}

function hbars(el, rows, { value, label, tip, suffix = '', max = 100 }) {
  el.innerHTML = rows.length ? rows.map((r, i) => {
    const v = value(r);
    return `<div class="hbar" data-i="${i}"><span>${esc(label(r))}</span>
      <span class="track"><span class="fill" data-pct="${Math.max(0, Math.min(100, v / max * 100))}"></span></span>
      <span class="val">${v}${suffix}</span></div>`;
  }).join('') : '<p class="muted">Нет данных.</p>';
  // Bar widths via CSSOM (allowed by the CSP), not inline style attributes.
  el.querySelectorAll('.fill[data-pct]').forEach((fill) => { fill.style.width = fill.dataset.pct + '%'; });
  el.querySelectorAll('.hbar').forEach((row) => {
    const r = rows[+row.dataset.i];
    row.addEventListener('mousemove', (e) => showTip(e, tip(r)));
    row.addEventListener('mouseleave', hideTip);
  });
}

function renderSkills(skills, weakest) {
  $('weakest-skill').innerHTML = weakest ? `Самый низкий средний результат среди критериев: <b>${esc(weakest.name)}</b> — ${esc(weakest.avg_pct)}%` : '';
  hbars($('skills'), skills, {
    value: (s) => s.avg_pct, label: (s) => s.name, suffix: '%',
    tip: (s) => `${esc(s.name)}<br/>Средний результат: <b>${s.avg_pct}%</b><br/>Оценок: ${s.samples}`,
  });
}

function renderProducts(products) {
  $('products').innerHTML = products.length ? `<tr><th scope="col">Продукт</th><th scope="col" class="num">Тренировок</th><th scope="col" class="num">Оценено</th><th scope="col" class="num">Средний балл</th><th scope="col" class="num">С критичной ошибкой</th></tr>` +
    products.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${esc(p.sessions)}</td><td class="num">${esc(p.scored)}</td><td class="num">${esc(p.avg_score ?? '—')}</td>
      <td class="num">${p.scored ? `${esc(p.sessions_with_critical_errors)} (${esc(p.critical_rate)}%)` : '—'}</td></tr>`).join('')
    : '<tr><td class="muted">Нет данных.</td></tr>';
}

function renderRisks(risks) {
  const c = risks.claims;
  const total = c.approved + c.unapproved + c.forbidden;
  const byType = risks.by_type;
  const maxCount = Math.max(1, ...byType.map((t) => t.count));
  $('risks').innerHTML = `
    <p class="small">Утверждения о продукте, сверенные с утверждённой базой знаний: <b>${total}</b> —
      <span class="verdict-approved">подтверждено ${c.approved}</span>,
      <span class="verdict-unapproved">не подтверждено базой знаний ${c.unapproved}</span>,
      <span class="verdict-forbidden">запрещено ${c.forbidden}</span></p>
    <h3>Критичные ошибки по типам</h3>${byType.length ? '' : '<p class="muted small">Критичных ошибок за период нет.</p>'}<div id="risk-bars"></div>`;
  hbars($('risk-bars'), byType, {
    value: (t) => t.count, label: (t) => t.type, max: maxCount,
    tip: (t) => `${esc(t.type)}<br/>Случаев: <b>${t.count}</b>`,
  });
}

const STATUS_BADGE = { finished: 'success', active: 'info', scoring: 'warning', finish_error: 'error' };

// Latest sessions of the team (named views only), newest first, as returned.
function renderRecent(rows, named) {
  $('recent-panel').classList.toggle('hidden', !named);
  if (!named) return;
  $('recent').innerHTML = rows.length ? `<div class="table-wrap"><table class="stack-table">
    <caption class="sr-only">Последние тренировки менеджеров команды</caption>
    <thead><tr><th scope="col">Менеджер</th><th scope="col">Дата</th><th scope="col">Сценарий</th><th scope="col">Статус</th><th scope="col">Балл</th><th scope="col">Разбор</th></tr></thead>
    <tbody>${rows.map((s) => `<tr>
      <td data-label="Менеджер"><a href="/manager?id=${esc(encodeURIComponent(s.user_id))}">${esc(s.full_name)}</a></td>
      <td data-label="Дата">${esc(fmtDate(s.started_at))}</td>
      <td data-label="Сценарий"><div>${esc(s.title)}</div><div class="muted small">${esc(s.product_name || s.product_id || '')} · ${esc(DIFFICULTY[s.difficulty] || s.difficulty || '')}</div></td>
      <td data-label="Статус"><span class="badge ${esc(STATUS_BADGE[s.status] || 'plain')}">${esc(SESSION_STATUS[s.status] || s.status)}</span></td>
      <td data-label="Балл">${s.total == null ? '<span class="muted">—</span>' : `<div class="status-cell"><b>${esc(s.total)}</b>${s.critical_errors ? '<span class="badge error">критичная ошибка</span>' : ''}</div>`}</td>
      <td data-label="Разбор"><a class="btn ghost small" href="/session?id=${esc(encodeURIComponent(s.id))}">${s.status === 'finished' ? 'Разбор' : 'Открыть'}</a></td></tr>`).join('')}</tbody></table></div>`
    : '<p class="muted">За период тренировок не было.</p>';
}

function renderDisputes(disputes, named) {
  const canSee = named || me.role === 'training';
  $('disputes-panel').classList.toggle('hidden', !canSee);
  $('disputes').innerHTML = disputes.length ? disputes.map((d) => `<div class="note-box mb-2">
      <div class="row small"><b>${d.total} баллов</b>${d.full_name ? ' · ' + esc(d.full_name) : ''}<span class="spacer"></span>${fmtDate(d.at)}
      ${named ? `<a href="/session?id=${encodeURIComponent(d.session_id)}">Разбор</a>` : ''}</div>${esc(d.comment)}</div>`).join('')
    : '<p class="muted">Возражений нет.</p>';
}

async function load() {
  const params = new URLSearchParams({ days: $('days').value });
  if ($('product').value) params.set('product_id', $('product').value);
  if ($('team').value) params.set('team_id', $('team').value);
  $('error').classList.add('hidden');
  try {
    const d = await api('/dashboard/data?' + params);
    if (d.teams.length && $('team').options.length === 1) {
      $('team').innerHTML += d.teams.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
      $('team').classList.remove('hidden');
    }
    renderKpis(d.kpi);
    renderTrend(d.trend);
    renderSkills(d.skills, d.weakest_skill);
    renderProducts(d.products);
    renderRisks(d.risks);
    renderRecent(d.recent_sessions, d.named);
    renderDisputes(d.disputes, d.named);
  } catch (err) {
    $('error').textContent = err.message;
    $('error').classList.remove('hidden');
  }
}

['days', 'product', 'team'].forEach((id) => $(id).addEventListener('change', load));

(async () => {
  me = await initPage('dashboard', 'can_dashboard');
  setPageHeader(
    me.role === 'sales_lead' ? `Обзор команды${me.team_name ? ' «' + me.team_name + '»' : ''}` : 'Обзор',
    'Результаты тренажёра — учебные данные. Они не влияют на KPI менеджеров.',
  );
  const products = await api('/products');
  $('product').innerHTML += products.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  load();
})();
