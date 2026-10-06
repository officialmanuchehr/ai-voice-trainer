// Manager drill-down for a lead (or admin): that manager's progress from
// /dashboard/managers/{id}/progress (the Phase 5B shape, rendered by
// progress-view.js) and their sessions from /dashboard/managers/{id}/sessions.
// The backend decides who may be viewed; presentation only.

const $ = (id) => document.getElementById(id);
const STATUS_BADGE = { finished: 'success', active: 'info', scoring: 'warning', finish_error: 'error' };

function sessionsPanel(rows) {
  if (!rows.length) return '';
  return `<section class="panel"><h2 class="mt-0">Тренировки</h2><div class="table-wrap"><table class="stack-table">
    <caption class="sr-only">Тренировки менеджера, новые сверху</caption>
    <thead><tr><th scope="col">Дата</th><th scope="col">Сценарий</th><th scope="col">Статус</th><th scope="col">Балл</th><th scope="col">Разбор</th></tr></thead>
    <tbody>${rows.map((s) => `<tr>
      <td data-label="Дата">${esc(fmtDate(s.started_at))}</td>
      <td data-label="Сценарий"><div>${esc(s.title)}</div><div class="muted small">${esc(s.product_name || s.product_id || '')} · ${esc(DIFFICULTY[s.difficulty] || s.difficulty || '')}</div></td>
      <td data-label="Статус"><span class="badge ${esc(STATUS_BADGE[s.status] || 'plain')}">${esc(SESSION_STATUS[s.status] || s.status)}</span></td>
      <td data-label="Балл">${s.total == null ? '<span class="muted">—</span>' : `<div class="status-cell"><b>${esc(s.total)}</b>${s.critical_errors ? '<span class="badge error">критичная ошибка</span>' : ''}${s.disputed ? '<span class="badge warning">оспорено</span>' : ''}</div>`}</td>
      <td data-label="Разбор"><a class="btn ghost small" href="/session?id=${esc(encodeURIComponent(s.id))}">${s.status === 'finished' ? 'Разбор' : 'Открыть'}</a></td></tr>`).join('')}</tbody></table></div></section>`;
}

function evaluatorNote(p) {
  if (!p.next_skill) return '';
  return `<section class="panel next-practice"><h2 class="m-0">Совет оценщика</h2>
    <div><div class="skill">${esc(p.next_skill.text)}</div>
    <div class="source-note">Из оценки тренировки от ${esc(fmtDate(p.next_skill.started_at))} —
      <a href="/session?id=${esc(encodeURIComponent(p.next_skill.session_id))}">открыть разбор</a></div></div></section>`;
}

(async () => {
  try {
    await initPage('team', 'can_dashboard');
  } catch { return; }
  const content = $('content');
  const id = new URLSearchParams(location.search).get('id') || '';
  try {
    const [p, history] = await Promise.all([
      api(`/dashboard/managers/${encodeURIComponent(id)}/progress`),
      api(`/dashboard/managers/${encodeURIComponent(id)}/sessions`),
    ]);
    setPageHeader(p.user.full_name, 'Тренировки и результаты менеджера — за всё время');
    if (!history.sessions.length) {
      content.innerHTML = `<div class="panel">${stateHtml('empty', 'Тренировок пока нет', 'Здесь появятся тренировки и результаты менеджера.')}</div>`;
      return;
    }
    if (!p.sessions.scored) {
      content.innerHTML = `<div class="stack"><div class="panel">${stateHtml('empty', 'Пока нет оценённых тренировок', '')}${scopeNote(p.sessions)}</div>${sessionsPanel(history.sessions)}</div>`;
      return;
    }
    renderProgress(content, p);
    content.querySelector('.stack').insertAdjacentHTML('beforeend', evaluatorNote(p) + sessionsPanel(history.sessions));
  } catch (err) {
    content.innerHTML = `<div class="panel">${stateHtml('error', 'Не удалось открыть данные менеджера', err.message)}</div>`;
  }
})();
