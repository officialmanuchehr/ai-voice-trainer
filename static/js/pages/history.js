// History: every training session of the current user (/me/sessions),
// newest first, with its stored status and result. Presentation only.

const $ = (id) => document.getElementById(id);

const STATUS_BADGE = { finished: 'success', active: 'info', scoring: 'warning', finish_error: 'error' };

function statusBadge(status) {
  return `<span class="badge ${esc(STATUS_BADGE[status] || 'plain')}">${esc(SESSION_STATUS[status] || status)}</span>`;
}

// Score cell: the stored final score (already capped by the backend) plus
// text badges, so meaning never depends on colour alone.
function scoreCell(s) {
  if (s.total == null) return '<span class="muted">—</span>';
  const badges = [];
  if (s.critical_errors) badges.push(`<span class="badge error">критичная ошибка${s.critical_errors > 1 ? ` ×${esc(s.critical_errors)}` : ''}</span>`);
  if (s.disputed) badges.push('<span class="badge warning">оспорено</span>');
  return `<div class="status-cell"><b>${esc(s.total)}</b>${badges.join('')}</div>`;
}

function actions(s) {
  const open = `<a class="btn ghost small" href="/session?id=${esc(encodeURIComponent(s.id))}">${s.status === 'finished' ? 'Разбор' : 'Открыть'}</a>`;
  const repeat = s.scenario_available
    ? `<a class="btn secondary small" href="/?repeat=${esc(encodeURIComponent(s.scenario_id))}">Повторить</a>`
    : '<span class="muted small">сценарий недоступен</span>';
  return `<div class="row">${open}${repeat}</div>`;
}

function sessionTable(rows) {
  return `<div class="table-wrap"><table class="stack-table">
    <caption class="sr-only">Ваши тренировки, новые сверху</caption>
    <thead><tr><th scope="col">Дата</th><th scope="col">Сценарий</th><th scope="col">Статус</th><th scope="col">Балл</th><th scope="col">Действия</th></tr></thead>
    <tbody>${rows.map((s) => `<tr>
      <td data-label="Дата">${esc(fmtDate(s.started_at))}</td>
      <td data-label="Сценарий"><div>${esc(s.title)}</div><div class="muted small">${esc(s.product_name || s.product_id || '')} · ${esc(DIFFICULTY[s.difficulty] || s.difficulty || '')}</div></td>
      <td data-label="Статус">${statusBadge(s.status)}</td>
      <td data-label="Балл">${scoreCell(s)}</td>
      <td data-label="Действия">${actions(s)}</td></tr>`).join('')}</tbody></table></div>`;
}

(async () => {
  try {
    await initPage('history');
  } catch { return; }
  const content = $('content');
  try {
    const rows = await api('/me/sessions');
    if (!rows.length) {
      content.innerHTML = `<div class="panel">${stateHtml('empty', 'Тренировок пока нет', 'Здесь появятся все ваши тренировки и их результаты.')}
        <div class="row justify-center"><a class="btn" href="/">Начать тренировку</a></div></div>`;
      return;
    }
    const unfinished = rows.some((s) => s.status === 'active');
    content.innerHTML = `<section class="panel">
      ${unfinished ? '<p class="scope-note mt-0">Тренировки «в процессе» не были завершены. Они сохранены, но продолжить их нельзя — начните новую тренировку по тому же сценарию кнопкой «Повторить».</p>' : ''}
      ${sessionTable(rows)}</section>`;
  } catch (err) {
    content.innerHTML = `<div class="panel">${stateHtml('error', 'Не удалось загрузить историю', err.message)}</div>`;
  }
})();
