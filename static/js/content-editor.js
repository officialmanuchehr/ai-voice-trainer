// Structured-editor toolkit (Phase 7). A form is rendered from a working copy
// of the stored object; every control is bound to one getter/setter, so an
// edit changes exactly that value and everything else — unknown fields,
// structured values, flags, order — is sent back as it was loaded.

class FormBinder {
  constructor(root, onChange) {
    this.root = root;
    this.onChange = onChange;
    this.bindings = [];
    this.actions = [];
    root.addEventListener('input', (e) => this.handle(e));
    root.addEventListener('change', (e) => this.handle(e));
    root.addEventListener('click', (e) => {
      const button = e.target.closest('[data-act]');
      if (!button || !root.contains(button)) return;
      const action = this.actions[+button.dataset.act];
      if (action) action();
    });
  }

  reset() {
    this.bindings = [];
    this.actions = [];
  }

  handle(e) {
    const el = e.target.closest('[data-bind]');
    if (!el || !this.root.contains(el)) return;
    const binding = this.bindings[+el.dataset.bind];
    if (!binding) return;
    binding.set(el.type === 'checkbox' ? el.checked : el.value);
    this.onChange(binding);
  }

  bind(get, set) {
    this.bindings.push({ get, set });
    return this.bindings.length - 1;
  }

  action(fn) {
    this.actions.push(fn);
    return this.actions.length - 1;
  }

  // ---- controls (all values escaped; ids are generated numbers)

  text(label, get, set, { key, multiline = false, help = '', disabled = false, required = false, type = 'text' } = {}) {
    const i = this.bind(get, set);
    const id = `ce-${i}`;
    const value = get() ?? '';
    const attrs = `id="${esc(id)}" data-bind="${esc(i)}" data-key="${esc(key || id)}"${disabled ? ' disabled' : ''}${required ? ' required aria-required="true"' : ''}`;
    const control = multiline
      ? `<textarea ${attrs} rows="3">${esc(value)}</textarea>`
      : `<input type="${esc(type)}" ${attrs} value="${esc(value)}"/>`;
    return `<div class="field"><label for="${esc(id)}">${esc(label)}${required ? ' <span class="muted">(обязательно)</span>' : ''}</label>${control}${help ? `<div class="field-help">${esc(help)}</div>` : ''}</div>`;
  }

  select(label, options, get, set, { key, disabled = false } = {}) {
    const i = this.bind(get, set);
    const id = `ce-${i}`;
    const current = get();
    const known = options.some(([value]) => value === current);
    // A stored value outside the list is shown as-is, never silently replaced.
    const all = known || current == null ? options : [[current, `${current} (текущее значение)`], ...options];
    return `<div class="field"><label for="${esc(id)}">${esc(label)}</label><select id="${esc(id)}" data-bind="${esc(i)}" data-key="${esc(key || id)}"${disabled ? ' disabled' : ''}>
      ${all.map(([value, text]) => `<option value="${esc(value)}"${value === current ? ' selected' : ''}>${esc(text)}</option>`).join('')}</select></div>`;
  }

  checkbox(label, get, set, { key, disabled = false, help = '' } = {}) {
    const i = this.bind(get, set);
    const id = `ce-${i}`;
    return `<div class="field"><label class="checkbox-row" for="${esc(id)}"><input type="checkbox" id="${esc(id)}" data-bind="${esc(i)}" data-key="${esc(key || id)}"${get() ? ' checked' : ''}${disabled ? ' disabled' : ''}/> ${esc(label)}</label>${help ? `<div class="field-help">${esc(help)}</div>` : ''}</div>`;
  }

  button(label, fn, { cls = 'secondary small', disabled = false, aria = '' } = {}) {
    const a = this.action(fn);
    return `<button type="button" class="${esc(cls)}" data-act="${esc(a)}"${disabled ? ' disabled' : ''}${aria ? ` aria-label="${esc(aria)}"` : ''}>${esc(label)}</button>`;
  }

  // A list of strings: one input per item, remove buttons, "add" button.
  stringList(label, getList, setList, { key, disabled = false, help = '', addLabel = 'Добавить', itemLabel = 'Пункт' } = {}) {
    const items = getList() || [];
    const rows = items.map((value, idx) => {
      const input = this.text(`${itemLabel} ${idx + 1}`, () => items[idx], (v) => { items[idx] = v; setList(items); }, { key: `${key}.${idx}`, disabled, multiline: String(value).length > 80 });
      const remove = disabled ? '' : this.button('Удалить', () => { items.splice(idx, 1); setList(items); this.onChange(null, true); }, { aria: `Удалить: ${itemLabel.toLowerCase()} ${idx + 1}` });
      return `<div class="list-row">${input}${remove}</div>`;
    }).join('');
    const add = disabled ? '' : this.button(addLabel, () => { items.push(''); setList(items); this.onChange(null, true, `${key}.${items.length - 1}`); });
    return `<fieldset class="list-field"><legend>${esc(label)}</legend>${help ? `<div class="field-help">${esc(help)}</div>` : ''}
      ${rows || '<p class="muted small m-0">Пусто.</p>'}${add ? `<div class="mt-1">${add}</div>` : ''}</fieldset>`;
  }
}

// Read-only display of stored fields the form does not edit. They are sent
// back unchanged.
function readOnlyFields(obj, keys) {
  const rows = keys.filter((k) => k in obj);
  if (!rows.length) return '';
  return `<dl class="facts readonly-fields">${rows.map((k) => `<dt>${esc(k)}</dt><dd><code>${esc(JSON.stringify(obj[k]))}</code></dd>`).join('')}</dl>`;
}

// ------------------------------------------------------------ confirm dialog

// Accessible confirmation (native <dialog>: focus is trapped and returned).
function confirmDialog({ title, body, confirmLabel, danger = false }) {
  let dialog = document.getElementById('confirm-dlg');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'confirm-dlg';
    dialog.setAttribute('aria-labelledby', 'confirm-title');
    document.body.appendChild(dialog);
  }
  const opener = document.activeElement;
  dialog.innerHTML = `<div class="dialog-head"><h2 id="confirm-title">${esc(title)}</h2></div>
    <div class="confirm-body">${body}</div>
    <div class="dialog-actions"><button type="button" class="secondary" data-answer="no">Отмена</button>
      <button type="button" class="${esc(danger ? 'danger' : '')}" data-answer="yes">${esc(confirmLabel)}</button></div>`;
  return new Promise((resolve) => {
    const done = (answer) => {
      dialog.close();
      if (opener && opener.focus) opener.focus();
      resolve(answer);
    };
    dialog.querySelector('[data-answer="no"]').addEventListener('click', () => done(false));
    dialog.querySelector('[data-answer="yes"]').addEventListener('click', () => done(true));
    dialog.addEventListener('cancel', (e) => { e.preventDefault(); done(false); }, { once: true });
    dialog.showModal();
    dialog.querySelector('[data-answer="no"]').focus();
  });
}

// ------------------------------------------------------------ unsaved changes

const unsaved = {
  dirty: false,
  set(value) { this.dirty = value; },
  // Asks before discarding edits; resolves true when it is fine to leave.
  async confirmLeave() {
    if (!this.dirty) return true;
    const ok = await confirmDialog({
      title: 'Есть несохранённые изменения',
      body: '<p class="m-0">Если уйти сейчас, изменения не сохранятся. Автосохранения нет.</p>',
      confirmLabel: 'Уйти без сохранения',
      danger: true,
    });
    if (ok) this.dirty = false;
    return ok;
  },
};
window.addEventListener('beforeunload', (e) => {
  if (unsaved.dirty) { e.preventDefault(); e.returnValue = ''; }
});
