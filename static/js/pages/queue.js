// Work queue for content roles: versions where this role has a next
// lifecycle step (from GET /admin/queue, decided by the backend's
// can_transition), KB drafts with review blockers, and — for roles with
// audit access — recent content changes. A view over the existing
// lifecycle; it adds no approval rules. Presentation only.

const $ = (id) => document.getElementById(id);
const STEP_TEXT = { approved: 'утвердить', published: 'опубликовать' };
const BADGE = { draft: 'plain', approved: 'warning', published: 'success', archived: 'plain' };

function badge(status) {
  return `<span class="badge ${esc(BADGE[status] || 'plain')}">${esc(CONTENT_STATUS_TEXT[status] || status)}</span>`;
}

function editorLink(item) {
  const tab = item.kind === 'kb' ? 'kb' : 'scenarios';
  return `/admin?tab=${tab}&open=${encodeURIComponent(item.id)}&v=${encodeURIComponent(item.version)}`;
}

function itemRows(items) {
  return `<div class="table-wrap"><table class="stack-table">
    <caption class="sr-only">Версии, ожидающие действия</caption>
    <thead><tr><th scope="col">Тип</th><th scope="col">Название</th><th scope="col">Версия</th><th scope="col">Ваш следующий шаг</th><th scope="col">Изменена</th><th scope="col"></th></tr></thead>
    <tbody>${items.map((i) => `<tr>
      <td data-label="Тип">${i.kind === 'kb' ? 'База знаний' : 'Сценарий'}</td>
      <td data-label="Название"><div>${esc(i.title)}</div><div class="muted small">${esc(i.product_name || i.product_id || '')}${i.live_version ? ` · действующая версия v${esc(i.live_version)}` : ' · нет опубликованной версии'}</div></td>
      <td data-label="Версия">v${esc(i.version)} ${badge(i.status)}</td>
      <td data-label="Ваш следующий шаг">${i.steps.length ? esc(i.steps.map((s) => STEP_TEXT[s]).join(' / ')) : 'исправить черновик'}
        ${i.blocked ? `<div class="status-cell"><span class="badge error">заблокировано</span><span class="small">${esc(i.blocked.detail)}</span></div>` : ''}</td>
      <td data-label="Изменена">${esc(fmtDate(i.updated_at))}<div class="muted small">${esc(i.author || '—')}</div></td>
      <td><a class="btn secondary small" href="${esc(editorLink(i))}">Открыть</a></td></tr>`).join('')}</tbody></table></div>`;
}

function blockerList(items) {
  return items.map((i) => `<div class="kb-entry">
    <div class="row"><b>${esc(i.title)}</b><span class="muted small">v${esc(i.version)}</span>${badge(i.status)}<span class="badge error">требует проверки: ${esc(i.review_blockers.length)}</span>
      <span class="spacer"></span><a class="btn secondary small" href="${esc(editorLink(i))}">Открыть</a></div>
    <ul class="small m-0">${i.review_blockers.map((b) => `<li>${esc(KB_SECTION_LABELS[b.section] || b.section)}${b.id ? ` — <code>${esc(b.id)}</code>` : ''}</li>`).join('')}</ul></div>`).join('');
}

const ACTION_TEXT = {
  'scenario.create': 'создал сценарий', 'scenario.edit_draft': 'изменил черновик сценария', 'scenario.new_version': 'создал новую версию сценария', 'scenario.status': 'сменил статус сценария',
  'kb.new_version': 'создал новую версию БЗ', 'kb.edit_draft': 'изменил черновик БЗ', 'kb.status': 'сменил статус БЗ',
};

function auditRows(rows) {
  if (!rows.length) return '<p class="muted">Изменений контента пока нет.</p>';
  return `<ul class="plain small">${rows.map((r) => {
    const d = r.details || {};
    const transition = d.from && d.to ? ` (${CONTENT_STATUS_TEXT[d.from] || d.from} → ${CONTENT_STATUS_TEXT[d.to] || d.to})` : '';
    const version = d.version ? ` v${d.version}` : '';
    return `<li>${esc(fmtDate(r.ts))} · <b>${esc(r.actor || '—')}</b> ${esc(ACTION_TEXT[r.action] || r.action)} <code>${esc(r.entity_id || '')}</code>${esc(version + transition)}</li>`;
  }).join('')}</ul>`;
}

(async () => {
  let me;
  try {
    me = await initPage('queue', 'can_content');
  } catch { return; }
  const content = $('content');
  try {
    const canAudit = me.role === 'admin' || me.role === 'compliance';
    const [queue, scnAudit, kbAudit] = await Promise.all([
      api('/admin/queue'),
      canAudit ? api('/admin/audit?limit=10&entity_type=scenario') : Promise.resolve([]),
      canAudit ? api('/admin/audit?limit=10&entity_type=knowledge_base') : Promise.resolve([]),
    ]);
    const ready = queue.items.filter((i) => i.steps.length);
    const blockers = queue.items.filter((i) => i.kind === 'kb' && i.review_blockers && i.review_blockers.length);
    const recent = [...scnAudit, ...kbAudit].sort((a, b) => b.id - a.id).slice(0, 10);
    content.innerHTML = `<div class="stack">
      <p class="scope-note m-0">Список строится по действующим правилам жизненного цикла и правам вашей роли. Это не отдельная процедура согласования: окончательное решение при каждом действии принимает система.</p>
      <section class="panel"><h2 class="mt-0">Ждут вашего действия <span class="muted small">(${esc(ready.length)})</span></h2>
        ${ready.length ? itemRows(ready) : stateHtml('empty', 'Нет версий, ожидающих действия вашей роли', '')}</section>
      <section class="panel"><h2 class="mt-0">Требует проверки в базе знаний <span class="muted small">(${esc(blockers.length)})</span></h2>
        <p class="muted small">Записи с пометкой «требует проверки» и пометки черновика блокируют утверждение и публикацию, пока их не снимут после проверки банком.</p>
        ${blockers.length ? blockerList(blockers) : stateHtml('empty', 'Непроверенных записей нет', '')}</section>
      ${canAudit ? `<section class="panel"><div class="section-head"><h2 class="m-0">Последние изменения контента</h2><a href="/admin?tab=audit">Журнал действий</a></div>${auditRows(recent)}</section>` : ''}
    </div>`;
  } catch (err) {
    content.innerHTML = `<div class="panel">${stateHtml('error', 'Не удалось загрузить задачи', err.message)}</div>`;
  }
})();
