// Application shell: sidebar (brand, role-aware navigation, user, theme,
// logout) and page header. Pages provide the static skeleton markup
// (#sidebar, #page-title, #page-subtitle, #page-actions, #main) and call
// initPage(activeKey, requiredFlag) first.
//
// Navigation visibility is UX only; the backend enforces every permission.
// The items come from /static/js/nav.json, whose role lists are checked
// against the real API by tests/test_phase4a.py.

const ICONS = {
  logo: '<path d="M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/><path d="M19 10v1a7 7 0 0 1-14 0v-1"/><path d="M12 18v3"/>',
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  team: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14.5a6.5 6.5 0 0 1 3.5 5.5"/>',
  mic: '<path d="M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"/><path d="M19 10v1a7 7 0 0 1-14 0v-1"/><path d="M12 18v3"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
  progress: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>',
  scenarios: '<path d="M4 5h16"/><path d="M4 12h16"/><path d="M4 19h10"/>',
  book: '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5Z"/><path d="M4 21.5A2.5 2.5 0 0 1 6.5 19H20v3H6.5"/>',
  users: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  audit: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h5"/>',
  queue: '<path d="M9 6h11"/><path d="M9 12h11"/><path d="M9 18h11"/><path d="m3 6 1.5 1.5L7 5"/><path d="m3 12 1.5 1.5L7 11"/><path d="m3 18 1.5 1.5L7 17"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
};

function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[name] || ''}</svg>`;
}

let _navConfig = null;
async function navConfig() {
  if (!_navConfig) _navConfig = await (await fetch('/static/js/nav.json')).json();
  return _navConfig;
}

function initials(name) {
  return (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('');
}

function renderSidebar(me, nav) {
  const sidebar = document.getElementById('sidebar');
  const groups = nav.groups
    .map((g) => ({ label: g.label, items: g.items.filter((item) => item.roles.includes(me.role)) }))
    .filter((g) => g.items.length);
  sidebar.innerHTML = `
    <a class="brand" href="/">
      <span class="brand-mark">${icon('logo')}</span>
      <span><span class="brand-name">AI Voice Trainer</span><br/><span class="brand-sub">Тренажёр продаж и комплаенса</span></span>
    </a>
    <nav aria-label="Разделы">
      ${groups.map((g) => `<div class="nav-group">
        ${groups.length > 1 ? `<div class="nav-group-label">${esc(g.label)}</div>` : ''}
        ${g.items.map((item) => `<a class="nav-link" href="${esc(item.href)}" data-nav="${esc(item.key)}">${icon(item.icon)}<span>${esc(item.label)}</span></a>`).join('')}
      </div>`).join('')}
    </nav>
    <div class="sidebar-footer">
      <div class="user-card" title="${esc(me.full_name || me.username)} · ${esc(me.role_name)}${me.team_name ? ' · ' + esc(me.team_name) : ''}">
        <span class="avatar" aria-hidden="true">${esc(initials(me.full_name || me.username))}</span>
        <div class="user-text">
          <div class="user-name">${esc(me.full_name || me.username)}</div>
          <div class="user-meta">${esc(me.role_name)}${me.team_name ? ' · ' + esc(me.team_name) : ''}</div>
        </div>
      </div>
      <div class="sidebar-actions" id="sidebar-actions">
        <button type="button" class="secondary small" id="logout-btn">${icon('logout')}Выйти</button>
      </div>
    </div>`;
  const select = themeSelect();
  select.classList.add('small');
  document.getElementById('sidebar-actions').prepend(select);
  document.getElementById('logout-btn').addEventListener('click', async (e) => {
    setLoading(e.currentTarget, true);
    await fetch('/auth/logout', { method: 'POST' }).catch(() => {});
    location.href = '/login';
  });
}

function setActiveNav(key) {
  document.querySelectorAll('#sidebar [data-nav]').forEach((link) => {
    if (link.dataset.nav === key) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}

function setPageHeader(title, subtitle) {
  if (title != null) {
    document.getElementById('page-title').textContent = title;
    document.title = `${title} — AI Voice Trainer`;
  }
  const sub = document.getElementById('page-subtitle');
  if (sub && subtitle != null) {
    sub.textContent = subtitle;
    sub.classList.toggle('hidden', !subtitle);
  }
}

function initMobileNav() {
  const shell = document.getElementById('app-shell');
  const toggle = document.getElementById('menu-toggle');
  if (!shell || !toggle) return;
  const close = () => { shell.classList.remove('nav-open'); toggle.setAttribute('aria-expanded', 'false'); };
  toggle.addEventListener('click', () => {
    const open = !shell.classList.contains('nav-open');
    shell.classList.toggle('nav-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) document.querySelector('#sidebar .nav-link')?.focus();
  });
  document.getElementById('sidebar-backdrop')?.addEventListener('click', close);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });
  document.getElementById('sidebar').addEventListener('click', (e) => { if (e.target.closest('.nav-link')) close(); });
}

// Loads the current user, builds the sidebar and guards the page. Throws
// (after rendering a "no access" state) when the role lacks requiredFlag.
async function initPage(active, requiredFlag) {
  const [me, nav] = await Promise.all([api('/auth/me'), navConfig()]);
  renderSidebar(me, nav);
  initMobileNav();
  if (active) setActiveNav(active);
  if (requiredFlag && !me[requiredFlag]) {
    setPageHeader('Нет доступа', '');
    document.getElementById('page-actions').innerHTML = '';
    document.getElementById('main').innerHTML = `<div class="page narrow"><div class="panel">${stateHtml('error', 'Недостаточно прав для этой страницы', 'Выберите раздел в меню слева.')}</div></div>`;
    throw new Error('forbidden');
  }
  return me;
}
