// Small shared UI helpers: toasts, page states (loading / empty / error) and
// button loading. Plain functions on purpose — no component framework.

function toast(message, kind = 'info') {
  let region = document.getElementById('toast-region');
  if (!region) {
    region = document.createElement('div');
    region.id = 'toast-region';
    region.className = 'toast-region';
    region.setAttribute('aria-live', 'polite');
    document.body.appendChild(region);
  }
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  el.innerHTML = `<span class="toast-text">${esc(message)}</span><button type="button" class="ghost small" aria-label="Закрыть">✕</button>`;
  el.querySelector('button').addEventListener('click', () => el.remove());
  region.appendChild(el);
  if (kind !== 'error') setTimeout(() => el.remove(), 5000);
  return el;
}

// HTML for a centred state block. kind: 'loading' | 'empty' | 'error'.
function stateHtml(kind, title, text) {
  const spinner = kind === 'loading' ? '<div class="spinner" aria-hidden="true"></div>' : '';
  const role = kind === 'error' ? ' role="alert"' : '';
  return `<div class="state ${kind}"${role}>${spinner}${title ? `<div class="state-title">${esc(title)}</div>` : ''}${text ? `<div>${esc(text)}</div>` : ''}</div>`;
}

function setLoading(button, loading) {
  if (!button) return;
  button.classList.toggle('is-loading', loading);
  button.disabled = loading;
  button.setAttribute('aria-busy', loading ? 'true' : 'false');
}
