// Dashboard: KPIs, weekly trend, skills, products, risks, managers (named
// views only), recommendations and disputes — all from /dashboard/data.

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
  return `<div class="kpi"><div class="label">${esc(label)}</div><div class="value">${value ?? '—'}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
}

function renderKpis(k) {
  $('kpis').innerHTML = [
    kpi('Тренировок', k.sessions_started, `оценено ${k.sessions_scored}${k.completion_rate != null ? ` · завершено ${k.completion_rate}%` : ''}`),
    kpi('Средний балл', k.avg_score, 'из 100'),
    kpi('Активные менеджеры', k.active_managers, k.total_managers ? `из ${k.total_managers}` : ''),
    kpi('Сессии с критичными ошибками', k.critical_session_rate != null ? k.critical_session_rate + '%' : null, 'продукт / комплаенс'),
    kpi('Время ответа AI-клиента', k.avg_latency_ms != null ? (k.avg_latency_ms / 1000).toFixed(1) + ' с' : null, 'цель — до 2–4 с'),
    kpi('Оспорено оценок', k.dispute_rate != null ? k.dispute_rate + '%' : null, 'от оценённых'),
  ].join('');
}

// Single-series line: average score per week, with the 60-point line as reference.
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
    ${grid}<line class="ref-line" x1="${L}" x2="${W - R}" y1="${y(60)}" y2="${y(60)}"/>
    <text class="axis-text" x="${W - R}" y="${y(60) - 4}" text-anchor="end">порог 60</text>
    ${xLabels}<path class="line" d="${path}"/>${dots}${hits}</svg>`;
  $('trend').querySelectorAll('rect[data-i]').forEach((r) => {
    const p = points[+r.dataset.i];
    r.addEventListener('mousemove', (e) => showTip(e, `Неделя с ${esc(p.week_start)}<br/>Средний балл: <b>${p.avg_score}</b><br/>Тренировок: ${p.sessions}`));
    r.addEventListener('mouseleave', hideTip);
  });
}

function hbars(el, rows, { value, label, tip, flag, suffix = '' , max = 100 }) {
  el.innerHTML = rows.length ? rows.map((r, i) => {
    const v = value(r);
    return `<div class="hbar" data-i="${i}"><span>${esc(label(r))}</span>
      <span class="track"><span class="fill" data-pct="${Math.max(0, Math.min(100, v / max * 100))}"></span></span>
      <span class="val">${flag && flag(r) ? '⚠ ' : ''}${v}${suffix}</span></div>`;
  }).join('') : '<p class="muted">Нет данных.</p>';
  // Bar widths via CSSOM (allowed by the CSP), not inline style attributes.
  el.querySelectorAll('.fill[data-pct]').forEach((fill) => { fill.style.width = fill.dataset.pct + '%'; });
  el.querySelectorAll('.hbar').forEach((row) => {
    const r = rows[+row.dataset.i];
    row.addEventListener('mousemove', (e) => showTip(e, tip(r)));
    row.addEventListener('mouseleave', hideTip);
  });
}

function renderSkills(skills) {
  hbars($('skills'), skills, {
    value: (s) => s.avg_pct, label: (s) => s.name, suffix: '%', flag: (s) => s.avg_pct < 60,
    tip: (s) => `${esc(s.name)}<br/>Средний результат: <b>${s.avg_pct}%</b><br/>Оценок: ${s.samples}`,
  });
}

function renderProducts(products) {
  $('products').innerHTML = products.length ? `<tr><th>Продукт</th><th class="num">Тренировок</th><th class="num">Средний балл</th><th class="num">С крит. ошибкой</th></tr>` +
    products.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${p.sessions}</td><td class="num">${p.avg_score ?? '—'}</td>
      <td class="num">${p.critical_rate != null ? (p.critical_rate >= 30 ? '<span class="flag-text">⚠ ' + p.critical_rate + '%</span>' : p.critical_rate + '%') : '—'}</td></tr>`).join('')
    : '<tr><td class="muted">Нет данных.</td></tr>';
}

function renderRisks(risks) {
  const c = risks.claims;
  const total = c.approved + c.unapproved + c.forbidden;
  const byType = risks.by_type;
  const maxCount = Math.max(1, ...byType.map((t) => t.count));
  $('risks').innerHTML = `
    <p class="small">Проверено продуктовых утверждений: <b>${total}</b> —
      <span class="verdict-approved">подтверждено ${c.approved}</span>,
      <span class="verdict-unapproved">нет в БЗ ${c.unapproved}</span>,
      <span class="verdict-forbidden">запрещено ${c.forbidden}</span></p>
    <h3>Критичные ошибки по типам</h3><div id="risk-bars"></div>`;
  hbars($('risk-bars'), byType, {
    value: (t) => t.count, label: (t) => t.type, max: maxCount,
    tip: (t) => `${esc(t.type)}<br/>Случаев: <b>${t.count}</b>`,
  });
}

function renderManagers(managers, named) {
  $('managers-panel').classList.toggle('hidden', !named);
  if (!named) return;
  $('managers').innerHTML = managers.length ? `<tr><th>Менеджер</th><th class="num">Тренировок</th><th class="num">Средний</th><th class="num">Первый → последний</th><th class="num">Крит. ошибки</th><th>Слабый навык</th><th>Нужна помощь</th></tr>` +
    managers.map((m) => `<tr>
      <td><button type="button" class="link" data-user="${esc(m.user_id)}">${esc(m.full_name)}</button></td>
      <td class="num">${m.sessions}</td><td class="num">${m.avg_score ?? '—'}</td>
      <td class="num">${m.first_score != null ? `${m.first_score} → ${m.last_score}` : '—'}</td>
      <td class="num">${m.critical_rate != null ? m.critical_rate + '%' : '—'}</td>
      <td>${esc(m.weakest_skill || '—')}</td>
      <td>${m.needs_help ? `<span class="flag-text">⚠ ${m.reasons.map(esc).join('; ')}</span>` : '<span class="muted">—</span>'}</td></tr>`).join('')
    : '<tr><td class="muted">В команде нет менеджеров.</td></tr>';
}

async function showManager(userId) {
  const el = $('manager-sessions');
  el.classList.remove('hidden');
  el.innerHTML = 'Загрузка…';
  try {
    const data = await api(`/dashboard/managers/${encodeURIComponent(userId)}/sessions`);
    el.innerHTML = `<h3>Тренировки: ${esc(data.user.full_name)}</h3><div class="table-wrap"><table>
      <tr><th>Дата</th><th>Сценарий</th><th>Статус</th><th class="num">Балл</th><th></th></tr>
      ${data.sessions.map((s) => `<tr><td>${fmtDate(s.started_at)}</td>
        <td>${esc(s.title)} <span class="muted small">v${s.scenario_version} · БЗ ${esc(s.kb_version)}</span></td>
        <td>${esc(SESSION_STATUS[s.status] || s.status)}${s.critical_errors ? ` <span class="flag-text small">⚠ ${s.critical_errors}</span>` : ''}${s.disputed ? ' <span class="chip">оспорено</span>' : ''}</td>
        <td class="num">${s.total ?? '—'}</td>
        <td>${s.status === 'finished' ? `<a href="/session?id=${encodeURIComponent(s.id)}">Разбор</a>` : ''}</td></tr>`).join('') || '<tr><td class="muted">Нет тренировок.</td></tr>'}
      </table></div>`;
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (err) {
    el.innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
  }
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
    renderSkills(d.skills);
    renderProducts(d.products);
    renderRisks(d.risks);
    renderManagers(d.managers, d.named);
    $('recommendations').innerHTML = d.recommendations.map((r) => `<li>${esc(r)}</li>`).join('') || '<li class="muted">Пока недостаточно данных.</li>';
    renderDisputes(d.disputes, d.named);
    $('manager-sessions').classList.add('hidden');
  } catch (err) {
    $('error').textContent = err.message;
    $('error').classList.remove('hidden');
  }
}

document.addEventListener('click', (e) => {
  const button = e.target.closest('[data-user]');
  if (button) showManager(button.dataset.user);
});
['days', 'product', 'team'].forEach((id) => $(id).addEventListener('change', load));

(async () => {
  me = await initPage(null, 'can_dashboard');
  const syncActiveNav = () => setActiveNav(me.role === 'sales_lead' && location.hash === '#managers-panel' ? 'team' : 'dashboard');
  syncActiveNav();
  window.addEventListener('hashchange', syncActiveNav);
  setPageHeader(
    me.role === 'sales_lead' ? `Обзор команды${me.team_name ? ' «' + me.team_name + '»' : ''}` : 'Обзор',
    'Результаты тренажёра — учебные данные. Они не влияют на KPI менеджеров.',
  );
  const products = await api('/products');
  $('product').innerHTML += products.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  load();
})();
