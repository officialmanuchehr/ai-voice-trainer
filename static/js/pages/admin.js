// Content administration: scenarios and knowledge base (structured editors,
// versions and statuses), users and teams, audit journal. Sections are opened
// from the sidebar via /admin?tab=…

const $ = (id) => document.getElementById(id);
let me, meta;

// Scenario and knowledge-base editors live in /static/js/scenario-editor.js
// and /static/js/kb-editor.js (structured forms over the stored content).

// ----------------------------------------------------------------- users

let users = [];
let teams = [];

const teamName = (id) => (teams.find((t) => t.id === id) || meta.teams.find((t) => t.id === id) || {}).name;

function filteredUsers() {
  const q = $('u-search').value.trim().toLowerCase();
  const role = $('u-filter-role').value;
  const team = $('u-filter-team').value;
  const active = $('u-filter-active').value;
  return users.filter((u) => (!q || u.username.toLowerCase().includes(q) || (u.full_name || '').toLowerCase().includes(q))
    && (!role || u.role === role)
    && (!team || (team === 'none' ? u.team_id == null : String(u.team_id) === team))
    && (!active || (active === 'active') === u.is_active));
}

function renderUsers() {
  const rows = filteredUsers();
  $('user-count').textContent = `Показано ${rows.length} из ${users.length}`;
  $('user-table').innerHTML = rows.length
    ? `<caption class="sr-only">Пользователи</caption><thead><tr><th scope="col">Пользователь</th><th scope="col">Роль</th><th scope="col">Команда</th><th scope="col">Статус</th><th scope="col"></th></tr></thead>
      <tbody>${rows.map((u) => `<tr>
        <td data-label="Пользователь"><div>${esc(u.full_name || u.username)}</div><div class="muted small">${esc(u.username)}</div></td>
        <td data-label="Роль">${esc(u.role_name)}</td><td data-label="Команда">${esc(teamName(u.team_id) || '—')}</td>
        <td data-label="Статус">${u.is_active ? '<span class="badge success">активен</span>' : '<span class="badge plain">отключён</span>'}</td>
        <td><button type="button" class="small secondary" data-edituser="${esc(u.id)}" aria-label="Изменить: ${esc(u.username)}">Изменить</button></td></tr>`).join('')}</tbody>`
    : `<tbody><tr><td>${stateHtml('empty', 'Пользователи не найдены', 'Измените поиск или фильтры.')}</td></tr></tbody>`;
}

async function loadUsers() {
  [users, teams] = await Promise.all([api('/admin/users'), api('/admin/teams')]);
  const teamOptions = teams.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
  $('u-team').innerHTML = '<option value="">—</option>' + teamOptions;
  const current = $('u-filter-team').value;
  $('u-filter-team').innerHTML = '<option value="">Все команды</option><option value="none">Без команды</option>' + teamOptions;
  $('u-filter-team').value = current;
  $('team-list').innerHTML = teams.length
    ? `<ul class="plain">${teams.map((t) => `<li><button type="button" class="link" data-team-filter="${esc(t.id)}">${esc(t.name)}</button> <span class="muted">· ${esc(t.members)} польз.</span></li>`).join('')}</ul>`
    : '<p class="muted m-0">Команд пока нет.</p>';
  renderUsers();
}

function resetUserForm() {
  $('user-form').reset();
  $('u-id').value = '';
  $('u-username').disabled = false;
  $('user-form-title').textContent = 'Новый пользователь';
  $('u-password').placeholder = 'мин. 8 символов';
  $('u-password').required = true;
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
  $('u-password').required = false;
  $('u-password').placeholder = 'оставьте пустым, чтобы не менять';
  $('user-form-title').textContent = 'Изменить: ' + u.username;
  $('user-msg').textContent = '';
  $('u-fullname').focus();
}

// Consequential changes (access, role, team, password) are listed and
// confirmed; a name change alone saves directly.
function userChanges(u, body, password) {
  const changes = [];
  if (u.is_active !== body.is_active) changes.push(body.is_active ? 'Включить вход (активировать учётную запись)' : 'Отключить вход — пользователь не сможет войти; его данные и история сохраняются');
  if (u.role !== body.role) changes.push(`Роль: ${meta.roles[u.role] || u.role} → ${meta.roles[body.role] || body.role} (меняет доступ к разделам и данным)`);
  if ((u.team_id ?? null) !== body.team_id) changes.push(`Команда: ${teamName(u.team_id) || 'без команды'} → ${teamName(body.team_id) || 'без команды'}${u.role === 'manager' || body.role === 'manager' ? ' (история тренировок станет видна руководителю новой команды)' : ''}`);
  if (password) changes.push('Задать новый пароль');
  return changes;
}

$('user-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('u-id').value;
  const body = {
    full_name: $('u-fullname').value, role: $('u-role').value,
    team_id: $('u-team').value ? parseInt($('u-team').value, 10) : null,
  };
  const password = $('u-password').value;
  try {
    if (id) {
      const u = users.find((x) => x.id === id);
      const full = { ...body, is_active: $('u-active').checked, password: password || null };
      const changes = userChanges(u, full, password);
      if (changes.length && !(await confirmDialog({
        title: `Изменить учётную запись ${u.username}?`,
        body: `<p class="m-0">Пользователь: <b>${esc(u.full_name || u.username)}</b> (${esc(u.username)})</p><ul>${changes.map((c) => `<li>${esc(c)}</li>`).join('')}</ul>`,
        confirmLabel: 'Сохранить изменения',
        danger: !full.is_active || u.role !== full.role,
      }))) return;
      await api(`/admin/users/${encodeURIComponent(id)}`, { method: 'PUT', json: full });
    } else {
      await api('/admin/users', { method: 'POST', json: { ...body, username: $('u-username').value, password } });
    }
    await loadUsers();
    resetUserForm();
    $('user-msg').textContent = 'Сохранено.';
  } catch (err) { $('user-msg').innerHTML = `<span class="flag-text">${esc(err.message)}</span>`; }
});
$('u-reset').addEventListener('click', resetUserForm);
['u-search', 'u-filter-role', 'u-filter-team', 'u-filter-active'].forEach((fid) => $(fid).addEventListener('input', renderUsers));
$('team-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api('/admin/teams', { method: 'POST', json: { name: $('team-name').value } });
    $('team-name').value = '';
    $('team-msg').textContent = 'Команда добавлена.';
    meta = await api('/admin/meta');
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

const statusText = (v) => CONTENT_STATUS_TEXT[v] || v;
const fieldValue = (field, v) => (field === 'role' ? meta.roles[v] || v : field === 'team_id' ? teamName(v) || (v == null ? 'без команды' : `команда ${v}`) : field === 'is_active' ? (v ? 'активен' : 'отключён') : v);
const FIELD_NAMES = { role: 'роль', team_id: 'команда', is_active: 'статус' };

// Readable, safe summary of the stored details (they never hold passwords,
// transcripts or content bodies).
function auditDetails(r) {
  const d = r.details || {};
  const parts = [];
  if (d.username) parts.push(`логин ${d.username}`);
  if (d.title) parts.push(`«${d.title}»`);
  if (d.version) parts.push(`v${d.version}`);
  if (d.from && d.to && typeof d.from === 'string') parts.push(`${statusText(d.from)} → ${statusText(d.to)}`);
  if (d.base_version) parts.push(`на основе v${d.base_version}`);
  if (d.scenario_id) parts.push(`сценарий ${d.scenario_id} v${d.scenario_version}`);
  if (d.kb_version) parts.push(`БЗ v${d.kb_version}`);
  if (d.total != null) parts.push(`балл ${d.total}`);
  if (Array.isArray(d.critical_errors) && d.critical_errors.length) parts.push(`критичные ошибки: ${d.critical_errors.join('; ')}`);
  if (r.action === 'user.create' && d.role) parts.push(`роль ${meta.roles[d.role] || d.role}`);
  Object.entries(FIELD_NAMES).forEach(([field, name]) => {
    const c = d[field];
    if (c && typeof c === 'object' && 'to' in c) parts.push(`${name}: ${fieldValue(field, c.from)} → ${fieldValue(field, c.to)}`);
    else if (r.action === 'user.edit' && field in d) parts.push(`${name}: ${fieldValue(field, d[field])}`);
  });
  if (d.password) parts.push('пароль изменён');
  if (d.name) parts.push(`«${d.name}»`);
  if (d.ip) parts.push(`IP ${d.ip}`);
  if (d.failures) parts.push(`неудачных попыток: ${d.failures}`);
  if (d.previous_failures) parts.push(`до входа неудачных попыток: ${d.previous_failures}`);
  return parts.join(' · ');
}

// Links only to places this role may open.
function auditObject(r) {
  const id = r.entity_id || '';
  if (r.entity_type === 'scenario' && id) {
    const v = (r.details || {}).version;
    return `<a href="/admin?tab=scenarios&open=${esc(encodeURIComponent(id))}${v ? `&v=${esc(encodeURIComponent(v))}` : ''}">${esc(id)}</a>`;
  }
  if (r.entity_type === 'knowledge_base' && id.includes('@')) {
    const [pid, ver] = id.split('@');
    return `<a href="/admin?tab=kb&open=${esc(encodeURIComponent(pid))}&v=${esc(encodeURIComponent(ver))}">${esc(id)}</a>`;
  }
  if (r.entity_type === 'session' && me.role === 'admin') return `<a href="/session?id=${esc(encodeURIComponent(id))}">${esc(id)}</a>`;
  return esc(id);
}

const ENTITY_TEXT = { session: 'Тренировка', scenario: 'Сценарий', knowledge_base: 'База знаний', user: 'Пользователь', team: 'Команда' };

async function loadAudit() {
  const params = new URLSearchParams({ limit: '300' });
  if ($('audit-filter').value) params.set('entity_type', $('audit-filter').value);
  if ($('audit-action').value) params.set('action', $('audit-action').value);
  if ($('audit-actor').value.trim()) params.set('actor', $('audit-actor').value.trim());
  const rows = await api('/admin/audit?' + params);
  $('audit-table').innerHTML = rows.length
    ? `<caption class="sr-only">Журнал действий, новые сверху</caption><thead><tr><th scope="col">Время</th><th scope="col">Кто</th><th scope="col">Действие</th><th scope="col">Объект</th><th scope="col">Детали</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td data-label="Время">${esc(fmtDate(r.ts))}</td><td data-label="Кто">${esc(r.actor || '—')}</td>
        <td data-label="Действие">${esc(ACTIONS[r.action] || r.action)}</td>
        <td data-label="Объект" class="small">${esc(ENTITY_TEXT[r.entity_type] || r.entity_type)}<br/>${auditObject(r)}</td>
        <td data-label="Детали" class="small">${esc(auditDetails(r)) || '—'}</td></tr>`).join('')}</tbody>`
    : `<tbody><tr><td>${stateHtml('empty', 'Событий по этому фильтру нет', '')}</td></tr></tbody>`;
}
$('audit-form').addEventListener('submit', (e) => { e.preventDefault(); loadAudit().catch((err) => toast(err.message, 'error')); });
$('audit-filter').addEventListener('change', () => loadAudit().catch((err) => toast(err.message, 'error')));
$('audit-action').addEventListener('change', () => loadAudit().catch((err) => toast(err.message, 'error')));

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

async function showTab(tab) {
  Object.keys(TABS).forEach((t) => $('tab-' + t).classList.toggle('hidden', t !== tab));
  setPageHeader(TABS[tab].title, TABS[tab].subtitle);
  setActiveNav(tab);
  await ({ scenarios: loadScenarios, kb: loadKb, users: loadUsers, audit: loadAudit })[tab]();
}

document.addEventListener('click', (e) => {
  const scn = e.target.closest('[data-open-scn]');
  if (scn) { openScenario(scn.dataset.openScn, scn.dataset.ver).catch((err) => toast(err.message, 'error')); return; }
  const kb = e.target.closest('[data-open-kb]');
  if (kb) { openKb(kb.dataset.openKb, kb.dataset.ver).catch((err) => toast(err.message, 'error')); return; }
  const team = e.target.closest('[data-team-filter]');
  if (team) { $('u-filter-team').value = team.dataset.teamFilter; renderUsers(); return; }
  const d = e.target.closest('[data-edituser]');
  if (d) editUser(d.dataset.edituser);
});
$('new-scenario').addEventListener('click', () => openScenario(null).catch((err) => toast(err.message, 'error')));
$('new-product').addEventListener('click', newProductDialog);

(async () => {
  me = await initPage(null, 'can_content');
  meta = await api('/admin/meta');
  $('new-scenario').classList.toggle('hidden', !meta.permissions.scenario_edit);
  $('new-product').classList.toggle('hidden', !meta.permissions.kb_edit);
  const roleOptions = Object.entries(meta.roles).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('');
  $('u-role').innerHTML = roleOptions;
  $('u-filter-role').innerHTML = '<option value="">Все роли</option>' + roleOptions;
  $('audit-action').innerHTML = '<option value="">Все действия</option>' + Object.entries(ACTIONS).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('');
  const params = new URLSearchParams(location.search);
  const start = params.get('tab');
  const fallback = me.role === 'product' || me.role === 'compliance' ? 'kb' : 'scenarios';
  const tab = tabAllowed(start) ? start : fallback;
  try {
    await showTab(tab);
    // Deep link from the work queue or the journal: ?tab=…&open=<id>&v=<version>
    const open = params.get('open');
    if (open && tab === 'scenarios') await openScenario(open, params.get('v') || (scenarioUi.items.find((s) => s.id === open)?.versions.slice(-1)[0]?.version));
    if (open && tab === 'kb') await openKb(open, params.get('v') || (kbUi.items.find((p) => p.product_id === open)?.versions.slice(-1)[0]?.version));
  } catch (err) { toast(err.message, 'error'); }
  history.replaceState(null, '', '/admin?tab=' + tab);
})();
