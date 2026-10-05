// Content administration: scenarios and knowledge base (versions and
// statuses), users and teams, audit journal. Sections are opened from the
// sidebar via /admin?tab=…

const $ = (id) => document.getElementById(id);
let me, meta;
const dlg = $('dlg');

function statusChip(v, label) {
  return `<span class="chip ${esc(v.status)}">${esc(label)} · ${esc(STATUS[v.status] || v.status)}</span>`;
}

function transitions(status, perms) {
  // [target, label, allowed]
  return {
    draft: [['approved', 'Утвердить', perms.approve], ['archived', 'В архив', perms.publish]],
    approved: [['published', 'Опубликовать', perms.publish], ['draft', 'Вернуть в черновик', perms.edit || perms.approve], ['archived', 'В архив', perms.publish]],
    published: [['archived', 'Снять с публикации (в архив)', perms.publish]],
    archived: [],
  }[status].filter((t) => t[2]);
}

function statusButtons(status, perms) {
  return transitions(status, perms).map(([to, label]) => `<button type="button" class="secondary" data-status="${to}">${label}</button>`).join('');
}

// ------------------------------------------------------------- scenarios

async function loadScenarios() {
  const items = await api('/admin/scenarios');
  const productName = Object.fromEntries(meta.products.map((p) => [p.id, p.name]));
  $('scenario-table').innerHTML = `<tr><th>Сценарий</th><th>Продукт</th><th>Сложность</th><th>Темы</th><th>Версии</th></tr>` +
    items.map((s) => `<tr>
      <td>${esc(s.title)}<div class="muted small">${esc(s.id)}${s.published_version ? ` · в работе v${s.published_version}` : ' · не опубликован'}</div></td>
      <td>${esc(productName[s.product_id] || s.product_id)}</td>
      <td><span class="chip ${esc(s.difficulty)}">${esc(DIFFICULTY[s.difficulty] || s.difficulty)}</span></td>
      <td><div class="versions">${(s.topics || []).map((t) => `<span class="chip topic">${esc(meta.topics[t] || t)}</span>`).join('') || '<span class="muted">—</span>'}</div></td>
      <td><div class="versions">${s.versions.map((v) => `<button type="button" class="link" data-scn="${esc(s.id)}" data-ver="${v.version}" title="${esc(v.author || '')} · ${fmtDate(v.updated_at || v.created_at)}">${statusChip(v, 'v' + v.version)}</button>`).join('')}</div></td>
    </tr>`).join('');
}

function scenarioForm(data, editable) {
  const rubric = meta.rubrics.find((r) => r.id === data.rubric_id) || meta.rubrics[0];
  const cfg = data.config || {};
  const w = cfg.criteria_weights || {};
  const dis = editable ? '' : 'disabled';
  return `
    <label class="field">Название<input type="text" id="s-title" value="${esc(data.title || '')}" ${dis}/></label>
    <div class="row">
      <label class="field flex-1">Продукт<select id="s-product" ${dis}>${meta.products.map((p) => `<option value="${esc(p.id)}" ${p.id === data.product_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
      <label class="field">Сложность<select id="s-difficulty" ${dis}>${meta.difficulties.map((d) => `<option value="${d}" ${d === data.difficulty ? 'selected' : ''}>${DIFFICULTY[d]}</option>`).join('')}</select></label>
      <label class="field">Рубрика<select id="s-rubric" ${dis}>${meta.rubrics.map((r) => `<option value="${esc(r.id)}" ${r.id === rubric.id ? 'selected' : ''}>${esc(r.title)}</option>`).join('')}</select></label>
    </div>
    <div class="field">Темы тренировки
      <div class="weights">${Object.entries(meta.topics).map(([id, name]) => `<label class="justify-start">
        <input type="checkbox" data-topic="${esc(id)}" ${(data.topics || []).includes(id) ? 'checked' : ''} ${dis}/>${esc(name)}</label>`).join('')}</div></div>
    <label class="field">Цель разговора (видит менеджер)<textarea id="s-goal" ${dis}>${esc(data.goal || '')}</textarea></label>
    <label class="field">Учебная цель<input type="text" id="s-learning" value="${esc(cfg.learning_goal || '')}" ${dis}/></label>
    <label class="field">Профиль клиента (JSON). Поля: business_type, industry, company_size, turnover, employees, owner, current_bank, current_products, business_context, current_situation, explicit_needs, pain, hidden_need, financial_literacy, style, emotion, urgency, decision_criteria, attitude_to_bank, trust_level, objections; <b>variants</b> — {поле: [варианты]} для генерации разных клиентов. Продуктовые условия сюда не пишутся — только в базу знаний.
      <textarea class="code compact" id="s-profile" ${dis}>${esc(JSON.stringify(data.client_profile || {}, null, 2))}</textarea></label>
    <div class="field">Веса критериев (итог нормируется к 100; 0 — критерий не учитывается)
      <div class="weights">${rubric.criteria.map((c) => `<label>${esc(c.name)}<input type="number" min="0" max="100" data-weight="${esc(c.id)}" value="${w[c.id] ?? c.weight}" ${dis}/></label>`).join('')}</div></div>
    <label class="field">Примеры хороших ответов (по одному в строке)<textarea id="s-good" ${dis}>${esc((cfg.good_examples || []).join('\n'))}</textarea></label>
    <label class="field">Подсказки для обратной связи (по одной в строке)<textarea id="s-hints" ${dis}>${esc((cfg.feedback_hints || []).join('\n'))}</textarea></label>`;
}

function readScenarioForm() {
  let profile;
  try { profile = JSON.parse($('s-profile').value); } catch (e) { throw new Error('Профиль клиента: неверный JSON — ' + e.message); }
  const rubric = meta.rubrics.find((r) => r.id === $('s-rubric').value);
  const weights = {};
  document.querySelectorAll('[data-weight]').forEach((i) => {
    const def = rubric.criteria.find((c) => c.id === i.dataset.weight).weight;
    const v = parseInt(i.value, 10);
    if (!Number.isNaN(v) && v !== def) weights[i.dataset.weight] = v;
  });
  const lines = (id) => $(id).value.split('\n').map((s) => s.trim()).filter(Boolean);
  return {
    title: $('s-title').value, product_id: $('s-product').value, difficulty: $('s-difficulty').value,
    rubric_id: $('s-rubric').value, goal: $('s-goal').value, client_profile: profile,
    topics: [...document.querySelectorAll('[data-topic]:checked')].map((i) => i.dataset.topic),
    config: { learning_goal: $('s-learning').value, criteria_weights: weights, good_examples: lines('s-good'), feedback_hints: lines('s-hints') },
  };
}

async function openScenario(id, version) {
  const isNew = !id;
  const v = isNew
    ? { status: 'draft', data: { title: '', product_id: meta.products[0]?.id, difficulty: 'medium', rubric_id: meta.rubrics[0].id, goal: '', client_profile: { business_type: '', owner: '', current_situation: '', pain: '', hidden_need: '', style: '', emotion: '', trust_level: '', objections: [], variants: {} }, config: {} } }
    : await api(`/admin/scenarios/${encodeURIComponent(id)}/versions/${version}`);
  const perms = { edit: meta.permissions.scenario_edit, approve: meta.permissions.scenario_approve, publish: meta.permissions.scenario_publish };
  const canEditDraft = perms.edit && v.status === 'draft';

  const render = (editable) => {
    $('dlg-body').innerHTML = `
      <div class="dialog-head"><h2 id="dlg-title">${isNew ? 'Новый сценарий' : esc(v.data.title) + ' · v' + v.version}</h2>
        ${isNew ? '' : statusChip(v, 'v' + v.version)}<button type="button" class="ghost small" id="dlg-close" aria-label="Закрыть">✕</button></div>
      ${isNew ? '' : `<p class="muted small">Автор: ${esc(v.author || '—')} · изменено ${fmtDate(v.updated_at || v.created_at)}${v.approved_by ? ' · утвердил ' + esc(v.approved_by) : ''}${v.published_at ? ' · опубликовано ' + fmtDate(v.published_at) : ''}</p>`}
      ${scenarioForm(v.data, editable)}
      <div id="dlg-msg" class="small"></div>
      <div class="dialog-actions">
        ${editable ? `<button type="button" id="dlg-save">${isNew ? 'Создать черновик' : v.status === 'draft' ? 'Сохранить черновик' : 'Сохранить как новую версию'}</button>` : ''}
        ${!editable && perms.edit && !isNew && v.status !== 'draft' ? '<button type="button" class="secondary" id="dlg-newver">Создать новую версию на основе этой</button>' : ''}
        ${isNew ? '' : statusButtons(v.status, perms)}
      </div>`;
    $('dlg-close').onclick = () => dlg.close();
    const msg = (t, err) => { $('dlg-msg').innerHTML = err ? `<div class="error-box">${esc(t)}</div>` : esc(t); };
    if ($('dlg-newver')) $('dlg-newver').onclick = () => render(true);
    if ($('dlg-save')) $('dlg-save').onclick = async () => {
      try {
        const data = readScenarioForm();
        const res = isNew ? await api('/admin/scenarios', { method: 'POST', json: { data } }) : await api(`/admin/scenarios/${encodeURIComponent(id)}`, { method: 'PUT', json: { data } });
        await loadScenarios();
        openScenario(res.id, res.version);
      } catch (err) { msg(err.message, true); }
    };
    $('dlg-body').querySelectorAll('[data-status]').forEach((b) => b.onclick = async () => {
      try {
        await api(`/admin/scenarios/${encodeURIComponent(id)}/versions/${version}/status`, { method: 'POST', json: { status: b.dataset.status } });
        await loadScenarios();
        openScenario(id, version);
      } catch (err) { msg(err.message, true); }
    });
  };
  render(isNew || canEditDraft);
  if (!dlg.open) dlg.showModal();
}

// ----------------------------------------------------------- knowledge base

async function loadKb() {
  const items = await api('/admin/kb');
  $('kb-table').innerHTML = `<tr><th>Продукт</th><th>Версии</th><th></th></tr>` +
    items.map((p) => `<tr>
      <td>${esc(p.name)}<div class="muted small">${esc(p.product_id)} · ${esc(p.segment)}</div></td>
      <td><div class="versions">${p.versions.map((v) => `<button type="button" class="link" data-kb="${esc(p.product_id)}" data-kbver="${esc(v.version)}" title="${esc(v.author || '')}">${statusChip(v, 'v' + v.version)}</button>`).join('')}</div></td>
      <td>${meta.permissions.kb_edit ? `<button class="small secondary" data-kbnew="${esc(p.product_id)}" data-latest="${esc(p.versions.length ? p.versions[p.versions.length - 1].version : '')}">Новая версия</button>` : ''}</td>
    </tr>`).join('');
}

function bumpVersion(v) {
  const parts = (v || '1.0.0').split('.').map((x) => parseInt(x, 10));
  if (parts.length === 3 && parts.every((x) => !Number.isNaN(x))) return `${parts[0]}.${parts[1] + 1}.0`;
  return v + '-2';
}

async function newKbVersion(productId, latest) {
  const version = prompt('Номер новой версии (копия последней версии):', bumpVersion(latest));
  if (!version) return;
  try {
    await api(`/admin/kb/${encodeURIComponent(productId)}/versions`, { method: 'POST', json: { version, base_version: latest || null } });
    await loadKb();
    openKb(productId, version);
  } catch (err) { toast(err.message, 'error'); }
}

function newProduct() {
  const template = { id: 'new_product', name: '', segment: '', rubric_id: meta.rubrics[0].id, goal: '', approved_facts: [{ id: 'fact_1', type: 'condition', text: '' }], approved_arguments: [], objections: [], disclaimers: [], forbidden: [], critical_errors: [] };
  $('dlg-body').innerHTML = `
    <div class="dialog-head"><h2 id="dlg-title">Новый продукт</h2><button type="button" class="ghost small" id="dlg-close" aria-label="Закрыть">✕</button></div>
    <div class="row"><label class="field flex-1">id продукта (a-z, 0-9, _)<input type="text" id="np-id" value="new_product"/></label>
      <label class="field">Версия<input type="text" id="np-ver" value="1.0.0"/></label></div>
    <label class="field">Содержимое (JSON; поле id должно совпадать)<textarea class="code" id="np-data">${esc(JSON.stringify(template, null, 2))}</textarea></label>
    <div id="dlg-msg"></div>
    <button id="np-save">Создать черновик</button>`;
  $('dlg-close').onclick = () => dlg.close();
  $('np-save').onclick = async () => {
    try {
      const data = JSON.parse($('np-data').value);
      const pid = $('np-id').value.trim();
      await api(`/admin/kb/${encodeURIComponent(pid)}/versions`, { method: 'POST', json: { version: $('np-ver').value.trim(), data } });
      meta = await api('/admin/meta');
      await loadKb();
      openKb(pid, $('np-ver').value.trim());
    } catch (err) { $('dlg-msg').innerHTML = `<div class="error-box">${esc(err.message)}</div>`; }
  };
  dlg.showModal();
}

async function openKb(productId, version) {
  const v = await api(`/admin/kb/${encodeURIComponent(productId)}/versions/${encodeURIComponent(version)}`);
  const perms = { edit: meta.permissions.kb_edit, approve: meta.permissions.kb_approve, publish: meta.permissions.kb_publish };
  const editable = perms.edit && v.status === 'draft';
  const review = (v.data.approved_facts || []).filter((f) => f.needs_review).length;
  $('dlg-body').innerHTML = `
    <div class="dialog-head"><h2 id="dlg-title">${esc(v.data.name)} · v${esc(v.version)}</h2>${statusChip(v, 'v' + v.version)}<button type="button" class="ghost small" id="dlg-close" aria-label="Закрыть">✕</button></div>
    <p class="muted small">Автор: ${esc(v.author || '—')} · ${fmtDate(v.updated_at || v.created_at)}${v.approved_by ? ' · утвердил ' + esc(v.approved_by) : ''}${v.published_at ? ' · опубликовано ' + fmtDate(v.published_at) : ''}</p>
    ${v.data.draft_note ? `<div class="note-box mb-2">${esc(v.data.draft_note)}</div>` : ''}
    ${review ? `<div class="note-box mb-2">Фактов с пометкой needs_review: <b>${review}</b>. Уберите пометку после проверки продуктовой командой.</div>` : ''}
    <label class="field">Содержимое (JSON): approved_facts, approved_arguments, objections (approved_response), disclaimers, forbidden, critical_errors
      <textarea class="code" id="kb-data" ${editable ? '' : 'readonly'}>${esc(JSON.stringify(v.data, null, 2))}</textarea></label>
    <label class="field">Комментарий к версии<input type="text" id="kb-notes" value="${esc(v.notes || '')}" ${editable ? '' : 'readonly'}/></label>
    <div id="dlg-msg"></div>
    <div class="row">${editable ? '<button id="kb-save">Сохранить черновик</button>' : ''}${statusButtons(v.status, perms)}</div>
    ${!editable && perms.edit ? '<p class="muted small">Эту версию нельзя редактировать. Чтобы внести изменения, создайте новую версию в списке.</p>' : ''}`;
  $('dlg-close').onclick = () => dlg.close();
  const fail = (err) => { $('dlg-msg').innerHTML = `<div class="error-box">${esc(err.message)}</div>`; };
  if ($('kb-save')) $('kb-save').onclick = async () => {
    try {
      const data = JSON.parse($('kb-data').value);
      await api(`/admin/kb/${encodeURIComponent(productId)}/versions/${encodeURIComponent(version)}`, { method: 'PUT', json: { data, notes: $('kb-notes').value } });
      await loadKb();
      openKb(productId, version);
    } catch (err) { fail(err); }
  };
  $('dlg-body').querySelectorAll('[data-status]').forEach((b) => b.onclick = async () => {
    try {
      await api(`/admin/kb/${encodeURIComponent(productId)}/versions/${encodeURIComponent(version)}/status`, { method: 'POST', json: { status: b.dataset.status } });
      meta = await api('/admin/meta');
      await loadKb();
      openKb(productId, version);
    } catch (err) { fail(err); }
  });
  if (!dlg.open) dlg.showModal();
}

// ----------------------------------------------------------------- users

let users = [];
let teams = [];

async function loadUsers() {
  [users, teams] = await Promise.all([api('/admin/users'), api('/admin/teams')]);
  const teamName = Object.fromEntries(teams.map((t) => [t.id, t.name]));
  $('user-table').innerHTML = `<tr><th>Пользователь</th><th>Роль</th><th>Команда</th><th></th></tr>` +
    users.map((u) => `<tr class="${u.is_active ? '' : 'muted'}">
      <td>${esc(u.full_name || u.username)}<div class="muted small">${esc(u.username)}${u.is_active ? '' : ' · отключён'}</div></td>
      <td>${esc(u.role_name)}</td><td>${esc(teamName[u.team_id] || '—')}</td>
      <td><button class="small secondary" data-edituser="${esc(u.id)}">Изменить</button></td></tr>`).join('');
  $('u-team').innerHTML = '<option value="">—</option>' + teams.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
  $('team-list').innerHTML = teams.map((t) => `${esc(t.name)} <span class="muted">(${t.members})</span>`).join(' · ') || '<span class="muted">Команд нет.</span>';
}

function resetUserForm() {
  $('user-form').reset();
  $('u-id').value = '';
  $('u-username').disabled = false;
  $('user-form-title').textContent = 'Новый пользователь';
  $('u-password').placeholder = 'мин. 8 символов';
  $('user-msg').textContent = '';
}

function editUser(id) {
  const u = users.find((x) => x.id === id);
  $('u-id').value = u.id;
  $('u-username').value = u.username;
  $('u-username').disabled = true;
  $('u-fullname').value = u.full_name;
  $('u-role').value = u.role;
  $('u-team').value = u.team_id ?? '';
  $('u-active').checked = u.is_active;
  $('u-password').value = '';
  $('u-password').placeholder = 'оставьте пустым, чтобы не менять';
  $('user-form-title').textContent = 'Изменить: ' + u.username;
  $('user-msg').textContent = '';
}

$('user-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('u-id').value;
  const body = {
    full_name: $('u-fullname').value, role: $('u-role').value,
    team_id: $('u-team').value ? parseInt($('u-team').value, 10) : null,
  };
  try {
    if (id) {
      await api(`/admin/users/${id}`, { method: 'PUT', json: { ...body, is_active: $('u-active').checked, password: $('u-password').value || null } });
    } else {
      await api('/admin/users', { method: 'POST', json: { ...body, username: $('u-username').value, password: $('u-password').value } });
    }
    await loadUsers();
    resetUserForm();
    $('user-msg').textContent = 'Сохранено.';
  } catch (err) { $('user-msg').innerHTML = `<span class="flag-text">${esc(err.message)}</span>`; }
});
$('u-reset').addEventListener('click', resetUserForm);
$('team-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/admin/teams', { method: 'POST', json: { name: $('team-name').value } });
    $('team-name').value = '';
    $('team-msg').textContent = '';
    await loadUsers();
  } catch (err) { $('team-msg').innerHTML = `<span class="flag-text">${esc(err.message)}</span>`; }
});

// ----------------------------------------------------------------- audit

const ACTIONS = {
  'auth.login': 'Вход', 'auth.login_failed': 'Неудачный вход', 'auth.login_throttled': 'Вход временно заблокирован', 'session.start': 'Начал тренировку', 'session.scored': 'Тренировка оценена', 'score.dispute': 'Оспорил оценку',
  'scenario.create': 'Создал сценарий', 'scenario.edit_draft': 'Изменил черновик сценария', 'scenario.new_version': 'Новая версия сценария', 'scenario.status': 'Статус сценария',
  'kb.new_version': 'Новая версия БЗ', 'kb.edit_draft': 'Изменил черновик БЗ', 'kb.status': 'Статус БЗ',
  'user.create': 'Создал пользователя', 'user.edit': 'Изменил пользователя', 'team.create': 'Создал команду',
};

async function loadAudit() {
  const type = $('audit-filter').value;
  const rows = await api('/admin/audit?limit=300' + (type ? '&entity_type=' + type : ''));
  $('audit-table').innerHTML = `<tr><th>Время</th><th>Кто</th><th>Действие</th><th>Объект</th><th>Детали</th></tr>` +
    rows.map((r) => `<tr><td>${fmtDate(r.ts)}</td><td>${esc(r.actor || '—')}</td><td>${esc(ACTIONS[r.action] || r.action)}</td>
      <td class="small">${esc(r.entity_type)}<br/>${r.entity_type === 'session' ? `<a href="/session?id=${encodeURIComponent(r.entity_id)}">${esc(r.entity_id)}</a>` : esc(r.entity_id || '')}</td>
      <td class="small"><code>${esc(JSON.stringify(r.details))}</code></td></tr>`).join('');
}
$('audit-filter').addEventListener('change', loadAudit);

// ------------------------------------------------------------------ wiring

// Sections are sidebar destinations (/admin?tab=…); the backend still
// enforces every permission, this only avoids opening a section in vain.
const TABS = {
  scenarios: { title: 'Сценарии', subtitle: 'Черновик → утверждено → опубликовано. Опубликованные версии не редактируются.' },
  kb: { title: 'База знаний', subtitle: 'Единственный источник продуктовой правды для AI-клиента и оценщика.' },
  users: { title: 'Пользователи и команды', subtitle: 'Учётные записи, роли и команды.', roles: ['admin'] },
  audit: { title: 'Журнал действий', subtitle: 'Кто, что и когда изменил.', roles: ['admin', 'compliance'] },
};

function tabAllowed(tab) {
  return TABS[tab] && (!TABS[tab].roles || TABS[tab].roles.includes(me.role));
}

function showTab(tab) {
  Object.keys(TABS).forEach((t) => $('tab-' + t).classList.toggle('hidden', t !== tab));
  setPageHeader(TABS[tab].title, TABS[tab].subtitle);
  setActiveNav(tab);
  history.replaceState(null, '', '/admin?tab=' + tab);
  ({ scenarios: loadScenarios, kb: loadKb, users: loadUsers, audit: loadAudit })[tab]().catch((err) => toast(err.message, 'error'));
}

document.addEventListener('click', (e) => {
  const a = e.target.closest('[data-scn], [data-kb]');
  if (a) {
    if (a.dataset.scn) openScenario(a.dataset.scn, a.dataset.ver);
    else openKb(a.dataset.kb, a.dataset.kbver);
    return;
  }
  const d = e.target.dataset || {};
  if (d.kbnew) newKbVersion(d.kbnew, d.latest);
  if (d.edituser) editUser(d.edituser);
});
$('new-scenario').addEventListener('click', () => openScenario(null));
$('new-product').addEventListener('click', newProduct);

(async () => {
  me = await initPage(null, 'can_content');
  meta = await api('/admin/meta');
  $('new-scenario').classList.toggle('hidden', !meta.permissions.scenario_edit);
  $('new-product').classList.toggle('hidden', !meta.permissions.kb_edit);
  $('u-role').innerHTML = Object.entries(meta.roles).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');
  const start = new URLSearchParams(location.search).get('tab');
  const fallback = me.role === 'product' || me.role === 'compliance' ? 'kb' : 'scenarios';
  showTab(tabAllowed(start) ? start : fallback);
})();
