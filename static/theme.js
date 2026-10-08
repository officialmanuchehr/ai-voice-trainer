// Colour theme: "system" (follow the device), "light" or "dark". Loaded in
// <head> so the saved choice applies before first paint — no flash of the
// wrong theme. The palettes themselves live in css/app.css (:root tokens).

const THEMES = { system: 'Как в системе', light: 'Светлая', dark: 'Тёмная' };
const THEME_KEY = 'avt-theme';

function getTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    return saved in THEMES ? saved : 'system';
  } catch {
    return 'system';
  }
}

function applyTheme(theme) {
  if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

function setTheme(theme) {
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* private mode: applies for this page only */ }
  applyTheme(theme);
}

function themeSelect() {
  const select = document.createElement('select');
  select.className = 'theme-select';
  select.title = 'Тема оформления';
  select.innerHTML = Object.entries(THEMES).map(([id, name]) => `<option value="${id}">${name}</option>`).join('');
  select.value = getTheme();
  select.addEventListener('change', () => setTheme(select.value));
  return select;
}

applyTheme(getTheme());
