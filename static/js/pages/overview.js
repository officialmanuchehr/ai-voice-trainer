// Manager overview: a short summary of the user's own training from
// /me/progress (all metrics are computed by the backend) and the latest
// sessions from /me/sessions. Presentation only — no analytics math here.

const $ = (id) => document.getElementById(id);

function kpi(label, value, sub) {
  return `<div class="kpi"><div class="label">${esc(label)}</div><div class="value">${value == null ? '—' : esc(value)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ''}</div>`;
}

function onboarding(name) {
  return `<section class="panel onboarding">
    <h2>Добро пожаловать${name ? ', ' + esc(name) : ''}!</h2>
    <p>Выберите сценарий и проведите разговор с AI-клиентом голосом или текстом. После завершения вы получите оценку по критериям и разбор ошибок, а здесь появится ваш прогресс.</p>
    <a class="btn" href="/">Начать первую тренировку</a></section>`;
}

function pendingNote(s) {
  const parts = [];
  if (s.in_progress) parts.push(`в процессе: ${s.in_progress}`);
  if (s.scoring) parts.push(`оценивается: ${s.scoring}`);
  if (s.scoring_failed) parts.push(`ошибка оценки: ${s.scoring_failed}`);
  return parts.length ? `<p class="scope-note">Показатели считаются только по оценённым тренировкам. Не учтены — ${esc(parts.join(', '))}.</p>` : '';
}

function nextPractice(p) {
  const blocks = [];
  if (p.next_skill) {
    blocks.push(`<div><div class="skill">${esc(p.next_skill.text)}</div>
      <div class="source-note">Совет из оценки тренировки от ${esc(fmtDate(p.next_skill.started_at))} —
        <a href="/session?id=${esc(encodeURIComponent(p.next_skill.session_id))}">открыть разбор</a></div></div>`);
  }
  if (p.weakest_criterion) {
    blocks.push(`<div>Самый низкий средний результат — <b>${esc(p.weakest_criterion.name)}</b> (${esc(p.weakest_criterion.avg_pct)}% от максимума).
      <a href="/progress">Подробнее</a></div>`);
  }
  if (!blocks.length) return '';
  return `<section class="panel next-practice"><h2 class="m-0">Что потренировать</h2>${blocks.join('')}</section>`;
}

function recent(rows) {
  const items = rows.slice(0, 5);
  return `<section class="panel"><div class="section-head"><h2 class="m-0">Последние тренировки</h2><a href="/history">Вся история</a></div>
    <div class="table-wrap"><table><thead><tr><th scope="col">Дата</th><th scope="col">Сценарий</th><th scope="col">Статус</th><th scope="col" class="num">Балл</th></tr></thead>
    <tbody>${items.map((s) => `<tr><td>${esc(fmtDate(s.started_at))}</td>
      <td><a href="/session?id=${esc(encodeURIComponent(s.id))}">${esc(s.title)}</a></td>
      <td>${esc(SESSION_STATUS[s.status] || s.status)}</td>
      <td class="num">${s.total == null ? '—' : esc(s.total)}${s.critical_errors ? ' <span class="badge error">крит.</span>' : ''}</td></tr>`).join('')}</tbody></table></div></section>`;
}

(async () => {
  let me;
  try {
    me = await initPage('overview');
  } catch { return; }
  const content = $('content');
  try {
    const [p, rows] = await Promise.all([api('/me/progress'), api('/me/sessions')]);
    const firstName = (me.full_name || '').split(' ')[0];
    if (!rows.length) { content.innerHTML = onboarding(firstName); return; }
    const s = p.summary;
    const kpis = p.sessions.scored ? `<div class="kpis">
      ${kpi('Оценённых тренировок', p.sessions.scored, '')}
      ${kpi('Средний балл', s.average_score, 'из 100')}
      ${kpi('Последний результат', s.latest_score, s.latest_at ? fmtDate(s.latest_at) : '')}
      ${kpi('С критичными ошибками', p.compliance.sessions_with_critical_errors, `из ${p.sessions.scored} оценённых`)}
    </div>
    ${p.sessions.scored > 1 ? `<p class="muted m-0">Первая оценённая тренировка: <b>${esc(s.first_score)}</b> · последняя: <b>${esc(s.latest_score)}</b>. <a href="/progress">Мой прогресс</a></p>` : ''}`
      : `<section class="panel">${stateHtml('empty', 'Пока нет оценённых тренировок', 'Показатели появятся после первой оценённой тренировки.')}</section>`;
    content.innerHTML = `<div class="stack">${kpis}${pendingNote(p.sessions)}${nextPractice(p)}${recent(rows)}</div>`;
  } catch (err) {
    content.innerHTML = `<div class="panel">${stateHtml('error', 'Не удалось загрузить обзор', err.message)}</div>`;
  }
})();
