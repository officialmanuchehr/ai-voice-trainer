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
  const scn = e.target.closest('[data-open-scn]');
  if (scn) { openScenario(scn.dataset.openScn, scn.dataset.ver).catch((err) => toast(err.message, 'error')); return; }
  const kb = e.target.closest('[data-open-kb]');
  if (kb) { openKb(kb.dataset.openKb, kb.dataset.ver).catch((err) => toast(err.message, 'error')); return; }
  const d = e.target.dataset || {};
  if (d.edituser) editUser(d.edituser);
});
$('new-scenario').addEventListener('click', () => openScenario(null).catch((err) => toast(err.message, 'error')));
$('new-product').addEventListener('click', newProductDialog);

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
