// Team: the managers of the lead's team with factual training indicators
// from /dashboard/data (team scope enforced by the backend). Alphabetical —
// no ranking, classification or thresholds. Presentation only.

const $ = (id) => document.getElementById(id);

function lastTraining(m) {
  if (!m.last_activity_at) return '<span class="muted">нет тренировок</span>';
  return esc(fmtDate(m.last_activity_at));
}

function results(m) {
  if (!m.scored) return '<span class="muted">нет оценённых</span>';
  return `<div>средний <b>${esc(m.avg_score)}</b> · последний <b>${esc(m.last_score)}</b></div>`;
}

function critical(m) {
  if (!m.scored) return '<span class="muted">—</span>';
  if (!m.critical_errors) return '<span class="muted">нет</span>';
  return `<div class="status-cell"><span class="badge error">${esc(m.critical_errors)} в ${esc(m.sessions_with_critical_errors)} трен.</span>${m.latest_has_critical_error ? '<span class="badge warning">в последней</span>' : ''}</div>`;
}

function weakest(m) {
  return m.weakest_skill ? `${esc(m.weakest_skill.name)} <span class="muted">· ${esc(m.weakest_skill.avg_pct)}%</span>` : '<span class="muted">—</span>';
}

function teamTable(managers) {
  return `<div class="table-wrap"><table class="stack-table">
    <caption class="sr-only">Менеджеры команды по алфавиту</caption>
    <thead><tr><th scope="col">Менеджер</th><th scope="col" class="num">Тренировок / оценено</th><th scope="col">Последняя тренировка</th>
      <th scope="col">Итоговый балл</th><th scope="col">Критичные ошибки</th><th scope="col">Самый низкий критерий</th></tr></thead>
    <tbody>${managers.map((m) => `<tr>
      <td data-label="Менеджер"><a href="/manager?id=${esc(encodeURIComponent(m.user_id))}">${esc(m.full_name)}</a></td>
      <td data-label="Тренировок / оценено" class="num">${esc(m.sessions)} / ${esc(m.scored)}</td>
      <td data-label="Последняя тренировка">${lastTraining(m)}</td>
      <td data-label="Итоговый балл">${results(m)}</td>
      <td data-label="Критичные ошибки">${critical(m)}</td>
      <td data-label="Самый низкий критерий">${weakest(m)}</td></tr>`).join('')}</tbody></table></div>`;
}

async function load() {
  const content = $('content');
  try {
    const d = await api('/dashboard/data?' + new URLSearchParams({ days: $('days').value }));
    if (!d.named) {
      content.innerHTML = `<div class="panel">${stateHtml('empty', 'Данные по сотрудникам недоступны', 'Для вашей роли доступна только общая статистика в разделе «Обзор».')}</div>`;
      return;
    }
    if (!d.managers.length) {
      content.innerHTML = `<div class="panel">${stateHtml('empty', 'В команде пока нет менеджеров', 'Менеджеров добавляет администратор.')}</div>`;
      return;
    }
    content.innerHTML = `<section class="panel">
      <p class="scope-note mt-0">Менеджеры по алфавиту. Показаны факты из тренировок за выбранный период: итоговый балл — сохранённая оценка (с ограничением 60 при критичных ошибках), критерии — средний процент от максимума. Это учебные данные, а не оценка сотрудника.</p>
      ${teamTable(d.managers)}</section>`;
  } catch (err) {
    content.innerHTML = `<div class="panel">${stateHtml('error', 'Не удалось загрузить команду', err.message)}</div>`;
  }
}

(async () => {
  let me;
  try {
    me = await initPage('team', 'can_dashboard');
  } catch { return; }
  if (me.role === 'sales_lead' && me.team_name) setPageHeader(`Команда «${me.team_name}»`, 'Тренировки менеджеров вашей команды');
  $('days').addEventListener('change', load);
  load();
})();
