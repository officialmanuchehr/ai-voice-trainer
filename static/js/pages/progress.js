// My progress: the user's own analytics exactly as /me/progress returns them.
// The backend owns every number (averages, normalisation, weakest/strongest,
// grouping); this page only lays them out. Each chart has a text equivalent.

const $ = (id) => document.getElementById(id);

function kpi(label, value, sub) {
  return `<div class="kpi"><div class="label">${esc(label)}</div><div class="value">${value == null ? '—' : esc(value)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ''}</div>`;
}

function scopeNote(s) {
  const excluded = [];
  if (s.in_progress) excluded.push(`в процессе: ${s.in_progress}`);
  if (s.scoring) excluded.push(`оценивается: ${s.scoring}`);
  if (s.scoring_failed) excluded.push(`ошибка оценки: ${s.scoring_failed}`);
  return `<p class="scope-note">Учитываются только оценённые тренировки (${esc(s.scored)}). Итоговый балл — сохранённая оценка, с учётом ограничения 60 при критичных ошибках.${excluded.length ? ` Не учтены — ${esc(excluded.join(', '))}.` : ''}</p>`;
}

// One point per scored session in chronological order; no interpolation, no target line.
// The viewBox follows the container width so axis text stays readable on phones.
function trendChart(points, width) {
  const W = Math.max(320, Math.min(960, width)), H = 260, L = 34, R = 16, T = 12, B = 28;
  const x = (i) => points.length === 1 ? L + (W - L - R) / 2 : L + i * (W - L - R) / (points.length - 1);
  const y = (v) => T + (100 - v) * (H - T - B) / 100;
  const grid = [0, 20, 40, 60, 80, 100].map((v) => `<line class="grid-line" x1="${esc(L)}" x2="${esc(W - R)}" y1="${esc(y(v))}" y2="${esc(y(v))}"/><text class="axis-text" x="${esc(L - 6)}" y="${esc(y(v) + 4)}" text-anchor="end">${v}</text>`).join('');
  const every = Math.ceil(points.length / 6);
  const labels = points.map((p, i) => i % every === 0 ? `<text class="axis-text" x="${esc(x(i))}" y="${esc(H - 8)}" text-anchor="middle">${esc(new Date(p.started_at).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }))}</text>` : '').join('');
  const path = points.length > 1 ? `<path class="line" d="${esc(points.map((p, i) => `${i ? 'L' : 'M'}${x(i)},${y(p.total)}`).join(' '))}"/>` : '';
  const dots = points.map((p, i) => `<circle class="dot" cx="${esc(x(i))}" cy="${esc(y(p.total))}" r="4"><title>${esc(fmtDate(p.started_at))}: ${esc(p.total)}</title></circle>`).join('');
  const label = `Итоговый балл по оценённым тренировкам: ${points.map((p) => p.total).join(', ')}`;
  return `<div class="chart-wrap wide"><svg viewBox="0 0 ${esc(W)} ${esc(H)}" role="img" aria-label="${esc(label)}">${grid}${labels}${path}${dots}</svg></div>`;
}

function trendTable(points) {
  return `<details class="mt-2"><summary>Таблица результатов</summary><div class="table-wrap mt-2"><table>
    <thead><tr><th scope="col">Дата</th><th scope="col">Сценарий</th><th scope="col" class="num">Балл</th><th scope="col" class="num">Критичные ошибки</th></tr></thead>
    <tbody>${points.map((p) => `<tr><td><a href="/session?id=${esc(encodeURIComponent(p.session_id))}">${esc(fmtDate(p.started_at))}</a></td><td>${esc(p.title)}</td>
      <td class="num">${esc(p.total)}</td><td class="num">${esc(p.critical_errors)}</td></tr>`).join('')}</tbody></table></div></details>`;
}

function criteriaBars(p) {
  const weakest = p.weakest_criterion && p.weakest_criterion.criterion_id;
  const strongest = p.strongest_criterion && p.strongest_criterion.criterion_id;
  const rows = p.criteria.map((c) => {
    const tag = c.criterion_id === weakest ? '<span class="badge warning skill-tag">слабее всего</span>'
      : c.criterion_id === strongest ? '<span class="badge success skill-tag">сильнее всего</span>' : '';
    return `<div class="hbar"><span>${esc(c.name)}${tag}</span>
      <span class="track" aria-hidden="true">${c.criterion_id === weakest ? '<span class="fill flag"' : '<span class="fill"'} data-pct="${esc(c.avg_pct)}"></span></span>
      <span class="val">${esc(c.avg_pct)}%</span></div>`;
  }).join('');
  return `<section class="panel"><h2 class="mt-0">Критерии</h2>
    <p class="muted small">Средний процент от максимума критерия по оценённым тренировкам — от слабого к сильному. У критериев разный максимум, поэтому сравниваются проценты, а не баллы.</p>
    ${rows}</section>`;
}

function productsTable(products) {
  return `<section class="panel"><h2 class="mt-0">Продукты</h2><div class="table-wrap"><table class="stack-table">
    <thead><tr><th scope="col">Продукт</th><th scope="col" class="num">Тренировок</th><th scope="col" class="num">Средний балл</th><th scope="col" class="num">С критичными ошибками</th></tr></thead>
    <tbody>${products.map((r) => `<tr><td data-label="Продукт">${esc(r.name || r.product_id)}</td><td class="num" data-label="Тренировок">${esc(r.sessions)}</td>
      <td class="num" data-label="Средний балл">${esc(r.avg_score)}</td><td class="num" data-label="С критичными ошибками">${esc(r.sessions_with_critical_errors)}</td></tr>`).join('')}</tbody></table></div></section>`;
}

function compliance(c, scored) {
  return `<section class="panel"><h2 class="mt-0">Точность и комплаенс</h2>
    <div class="kpis">
      ${kpi('Критичных ошибок', c.critical_errors, `в ${c.sessions_with_critical_errors} из ${scored} тренировок`)}
      ${kpi('Подтверждённые утверждения', c.claims.approved, 'есть в базе знаний')}
      ${kpi('Неподтверждённые', c.claims.unapproved, 'нет в утверждённых материалах')}
      ${kpi('Запрещённые', c.claims.forbidden, 'противоречат правилам')}
    </div>
    <p class="muted small mb-2 mt-2">Утверждения о продукте сверяются с утверждённой базой знаний. Подробности — в разборе каждой тренировки.</p></section>`;
}

(async () => {
  try {
    await initPage('progress');
  } catch { return; }
  const content = $('content');
  try {
    const p = await api('/me/progress');
    if (!p.sessions.scored) {
      content.innerHTML = `<div class="panel">${stateHtml('empty', 'Пока нет оценённых тренировок', 'Прогресс появится после первой тренировки, получившей оценку.')}
        ${scopeNote(p.sessions)}<div class="row justify-center"><a class="btn" href="/">Начать тренировку</a></div></div>`;
      return;
    }
    const s = p.summary;
    content.innerHTML = `<div class="stack">
      ${scopeNote(p.sessions)}
      <div class="kpis">
        ${kpi('Средний балл', s.average_score, 'из 100')}
        ${kpi('Первая оценённая', s.first_score, '')}
        ${kpi('Последняя', s.latest_score, s.latest_at ? fmtDate(s.latest_at) : '')}
        ${kpi('Оценённых тренировок', p.sessions.scored, '')}
      </div>
      <section class="panel"><h2 class="mt-0">Итоговый балл по тренировкам</h2>${trendChart(p.score_trend, content.clientWidth - 48)}${trendTable(p.score_trend)}</section>
      ${p.criteria.length ? criteriaBars(p) : ''}
      ${p.products.length ? productsTable(p.products) : ''}
      ${compliance(p.compliance, p.sessions.scored)}
    </div>`;
    content.querySelectorAll('.fill[data-pct]').forEach((fill) => { fill.style.width = Math.max(0, Math.min(100, Number(fill.dataset.pct) || 0)) + '%'; });
  } catch (err) {
    content.innerHTML = `<div class="panel">${stateHtml('error', 'Не удалось загрузить прогресс', err.message)}</div>`;
  }
})();
