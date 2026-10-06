// Knowledge-base list and structured editor (Phase 7). The KB is the only
// source of product truth: this editor never fills in, rewrites or clears
// bank content by itself. It edits a working copy of the stored version and
// sends back every field it does not edit exactly as loaded (fact `value`,
// `exercise_type`, `rubric_id`, `goal`, unknown keys …).

const kbUi = { items: [], current: null };

// Fields each section's form edits; anything else is shown read-only.
const KB_ENTRY_FIELDS = {
  approved_facts: ['id', 'type', 'text', 'value', 'needs_review', 'compliance_owned', 'compliance_note'],
  approved_arguments: ['id', 'text', 'needs_review', 'compliance_owned', 'compliance_note'],
  objections: ['id', 'trigger', 'approved_response', 'needs_review', 'compliance_owned', 'compliance_note'],
  disclaimers: ['id', 'text', 'needs_review', 'compliance_owned', 'compliance_note'],
};
const KB_TOP_FIELDS = ['id', 'name', 'segment', 'draft_note', 'approved_facts', 'approved_arguments', 'objections', 'disclaimers', 'forbidden', 'critical_errors'];
const KB_ID_PREFIX = { approved_facts: 'fact', approved_arguments: 'arg', objections: 'obj', disclaimers: 'disc' };
const KB_ENTRY_NAME = { approved_facts: 'Факт', approved_arguments: 'Аргумент', objections: 'Возражение', disclaimers: 'Оговорка' };

const kbPerms = () => ({ edit: meta.permissions.kb_edit, approve: meta.permissions.kb_approve, publish: meta.permissions.kb_publish });

// ------------------------------------------------------------------ list

async function loadKb() {
  showKbList();
  kbUi.items = await api('/admin/kb');
  const rows = kbUi.items.map((p) => {
    const published = p.versions.find((v) => v.status === 'published');
    const latest = p.versions[p.versions.length - 1];
    return `<tr>
      <td data-label="Продукт"><div>${esc(p.name)}</div><div class="muted small">${esc(p.product_id)} · ${esc(p.segment)}</div></td>
      <td data-label="Опубликована">${published ? `v${esc(published.version)}${published.review_blockers ? ` <span class="badge error">на проверке: ${esc(published.review_blockers)}</span>` : ''}` : '<span class="muted">нет</span>'}</td>
      <td data-label="Версии"><div class="versions">${p.versions.map((v) => `<span class="version-chip">v${esc(v.version)} ${statusBadge(v.status)}${v.review_blockers ? ` <span class="badge error">на проверке: ${esc(v.review_blockers)}</span>` : ''}</span>`).join('') || '<span class="muted">нет версий</span>'}</div></td>
      <td data-label="Действия">${latest ? `<button type="button" class="secondary small" data-open-kb="${esc(p.product_id)}" data-ver="${esc(latest.version)}">Открыть</button>` : ''}</td></tr>`;
  }).join('');
  $('kb-table').innerHTML = rows
    ? `<caption class="sr-only">Продукты и версии базы знаний</caption><thead><tr><th scope="col">Продукт</th><th scope="col">Опубликована</th><th scope="col">Версии</th><th scope="col">Действия</th></tr></thead><tbody>${rows}</tbody>`
    : `<tbody><tr><td>${stateHtml('empty', 'Продуктов пока нет', '')}</td></tr></tbody>`;
}

function showKbList() {
  $('kb-list').classList.remove('hidden');
  $('kb-editor').classList.add('hidden');
}

// ---------------------------------------------------------------- editor

async function openKb(productId, version) {
  if (!(await unsaved.confirmLeave())) return;
  const v = await api(`/admin/kb/${encodeURIComponent(productId)}/versions/${encodeURIComponent(version)}`);
  if (!kbUi.items.length) kbUi.items = await api('/admin/kb');
  const product = kbUi.items.find((p) => p.product_id === productId);
  kbUi.current = { productId, version: v.version, meta: v, product, data: deepClone(v.data), notes: v.notes || '' };
  unsaved.set(false);
  $('kb-list').classList.add('hidden');
  $('kb-editor').classList.remove('hidden');
  renderKbEditor();
  $('kb-editor').querySelector('h2').focus();
}

let kbBinder = null;
function renderKbEditor(focusKey) {
  const root = $('kb-editor');
  if (!kbBinder) kbBinder = new FormBinder(root, (binding, structural, key) => {
    unsaved.set(true);
    $('kb-dirty').textContent = 'Есть несохранённые изменения';
    if (structural) renderKbEditor(key);
    else refreshKbBlockers();
  });
  const b = kbBinder;
  b.reset();
  const st = kbUi.current;
  const d = st.data;
  const perms = kbPerms();
  const editable = perms.edit && st.meta.status === 'draft';
  const dis = !editable;
  const optionalText = (obj, key) => (val) => { if (val === '') delete obj[key]; else obj[key] = val; };
  const flag = (obj, key) => (on) => { if (on) obj[key] = true; else delete obj[key]; };
  // Numbers stay numbers: an empty or non-numeric entry in a numeric field is
  // held back (and reported on save) instead of being stored as text.
  st.invalid = st.invalid || new Set();
  const numberSafe = (obj, key, path) => {
    const numeric = typeof obj[key] === 'number';
    return (val) => {
      const typed = typedValue(obj[key], val);
      if (numeric && typeof typed !== 'number') { st.invalid.add(path); return; }
      st.invalid.delete(path);
      obj[key] = typed;
    };
  };
  const types = [...new Set((d.approved_facts || []).map((f) => f.type).filter(Boolean))];

  const valueEditor = (entry, section, idx) => {
    if (!('value' in entry)) return '';
    const value = entry.value;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const fields = Object.keys(value).map((k) => (value[k] !== null && typeof value[k] === 'object'
        ? `<div class="field"><span class="field-label">${esc(k)}</span><code>${esc(JSON.stringify(value[k]))}</code></div>`
        : typeof value[k] === 'boolean'
          ? b.checkbox(k, () => value[k], (on) => { value[k] = on; }, { key: `${section}.${idx}.value.${k}`, disabled: dis })
          : b.text(k, () => value[k], numberSafe(value, k, `${section}.${idx}.value.${k}`), { key: `${section}.${idx}.value.${k}`, disabled: dis, type: typeof value[k] === 'number' ? 'number' : 'text' }))).join('');
      return `<fieldset class="list-field"><legend>Структурированное значение факта</legend>
        <div class="field-help">Должно совпадать с текстом факта. Набор полей не меняется в редакторе.</div><div class="form-grid">${fields}</div></fieldset>`;
    }
    if (value === null || typeof value === 'object') return `<div class="field"><span class="field-label">Значение (только просмотр)</span><code>${esc(JSON.stringify(value))}</code></div>`;
    return b.text('Значение факта', () => entry.value, numberSafe(entry, 'value', `${section}.${idx}.value`), { key: `${section}.${idx}.value`, disabled: dis, type: typeof value === 'number' ? 'number' : 'text' });
  };

  const entryCard = (section, entry, idx) => {
    if (!entry || typeof entry !== 'object') return `<div class="kb-entry"><code>${esc(JSON.stringify(entry))}</code></div>`;
    const k = `${section}.${idx}`;
    const fields = [b.text('id', () => entry.id, (val) => { entry.id = val; }, { key: `${k}.id`, disabled: dis, required: true })];
    if (section === 'approved_facts') {
      fields.push(b.text('Тип факта', () => entry.type, optionalText(entry, 'type'), { key: `${k}.type`, disabled: dis, help: types.length ? `Используемые типы: ${types.join(', ')}` : '' }));
      fields.push(b.text('Текст факта', () => entry.text, (val) => { entry.text = val; }, { key: `${k}.text`, disabled: dis, multiline: true, required: true }));
      fields.push(valueEditor(entry, section, idx));
    } else if (section === 'objections') {
      fields.push(b.text('Возражение клиента', () => entry.trigger, (val) => { entry.trigger = val; }, { key: `${k}.trigger`, disabled: dis, multiline: true, required: true }));
      fields.push(b.text('Утверждённый ответ', () => entry.approved_response, (val) => { entry.approved_response = val; }, { key: `${k}.approved_response`, disabled: dis, multiline: true, required: true }));
    } else {
      fields.push(b.text('Текст', () => entry.text, (val) => { entry.text = val; }, { key: `${k}.text`, disabled: dis, multiline: true, required: true }));
    }
    fields.push(`<div class="review-controls">
      ${b.checkbox('Требует проверки — блокирует утверждение и публикацию', () => entry.needs_review, flag(entry, 'needs_review'), { key: `${k}.needs_review`, disabled: dis, help: 'Снимайте отметку только после подтверждения содержания банком.' })}
      ${b.checkbox('Формулировка за комплаенсом', () => entry.compliance_owned, flag(entry, 'compliance_owned'), { key: `${k}.compliance_owned`, disabled: dis })}
      ${b.text('Комментарий комплаенса (справочно, сам по себе не блокирует)', () => entry.compliance_note, optionalText(entry, 'compliance_note'), { key: `${k}.compliance_note`, disabled: dis, multiline: true })}
    </div>`);
    const extra = Object.keys(entry).filter((key) => !KB_ENTRY_FIELDS[section].includes(key));
    if (extra.length) fields.push(`<div class="field"><span class="field-label">Другие поля (сохраняются без изменений)</span>${readOnlyFields(entry, extra)}</div>`);
    const badges = [
      entry.needs_review ? '<span class="badge error">требует проверки</span>' : '',
      entry.compliance_owned ? '<span class="badge info">за комплаенсом</span>' : '',
      entry.compliance_note ? '<span class="badge warning">есть комментарий комплаенса</span>' : '',
    ].join('');
    const remove = editable ? b.button('Удалить запись', () => { d[section].splice(idx, 1); b.onChange(null, true); }, { aria: `Удалить ${KB_ENTRY_NAME[section].toLowerCase()} ${entry.id || idx + 1}` }) : '';
    return `<div class="kb-entry${esc(entry.needs_review ? ' needs-review' : '')}" id="kbe-${esc(section)}-${esc(idx)}">
      <div class="row"><b>${esc(KB_ENTRY_NAME[section])} ${esc(idx + 1)}</b><code class="muted small">${esc(entry.id || '')}</code>${badges}<span class="spacer"></span>${remove}</div>
      ${fields.join('')}</div>`;
  };

  const sectionPanel = (section) => {
    const entries = d[section] || [];
    const add = editable ? b.button(`Добавить: ${KB_ENTRY_NAME[section].toLowerCase()}`, () => {
      d[section] = d[section] || [];
      const entry = section === 'objections' ? { id: freshId(d[section], KB_ID_PREFIX[section]), trigger: '', approved_response: '' } : { id: freshId(d[section], KB_ID_PREFIX[section]), text: '' };
      d[section].push(entry);
      b.onChange(null, true, `${section}.${d[section].length - 1}.${section === 'objections' ? 'trigger' : 'text'}`);
    }) : '';
    return `<section class="panel"><h3 class="mt-0">${esc(KB_SECTION_LABELS[section])} <span class="muted small">(${esc(entries.length)})</span></h3>
      ${entries.map((entry, idx) => entryCard(section, entry, idx)).join('') || '<p class="muted small">Записей нет.</p>'}
      ${add ? `<div class="mt-2">${add}</div>` : ''}</section>`;
  };

  const extraTop = Object.keys(d).filter((key) => !KB_TOP_FIELDS.includes(key));
  const versions = st.product ? st.product.versions : [];
  const published = versions.find((x) => x.status === 'published');

  const actions = [];
  if (editable) actions.push(b.button('Сохранить черновик', saveKb, { cls: '' }));
  if (perms.edit) actions.push(b.button('Создать новую версию', () => newKbVersionDialog(st.productId, st.version)));
  allowedTransitions(st.meta.status, perms).forEach(([to, label]) => actions.push(b.button(label, () => changeKbStatus(to), { cls: to === 'archived' ? 'secondary small danger-text' : 'secondary small' })));

  const banner = editable
    ? `Черновик v${st.version}. Изменения сохраняются в эту версию; опубликованная версия${published ? ` v${published.version}` : ''} не меняется.`
    : `Версия v${st.version} · ${CONTENT_STATUS_TEXT[st.meta.status]}. ${st.meta.status === 'draft' ? 'Только просмотр для вашей роли.' : 'Утверждённые, опубликованные и архивные версии не редактируются — изменения вносятся в новой версии.'}`;

  root.innerHTML = `
    <div class="row mb-2">${b.button('← Все продукты', async () => { if (await unsaved.confirmLeave()) { unsaved.set(false); loadKb(); } }, { cls: 'ghost small' })}</div>
    <section class="panel">
      <div class="row"><h2 class="m-0" tabindex="-1">${esc(d.name || st.productId)} · v${esc(st.version)}</h2>${statusBadge(st.meta.status)}${published && published.version === st.version ? '<span class="badge success">действующая версия</span>' : ''}</div>
      <p class="muted small">Продукт <code>${esc(st.productId)}</code> · автор: ${esc(st.meta.author || '—')} · изменено ${esc(fmtDate(st.meta.updated_at || st.meta.created_at))}${st.meta.approved_by ? ' · утвердил ' + esc(st.meta.approved_by) : ''}${st.meta.published_at ? ' · опубликовано ' + esc(fmtDate(st.meta.published_at)) : ''}</p>
      <p class="note-box">${esc(banner)}</p>
      <div id="kb-blockers"></div>
      <div id="kb-msg" role="alert"></div>
      <div class="row editor-actions">${actions.join('')}<span class="muted small" id="kb-dirty" role="status"></span></div>
      ${b.text('Комментарий к версии', () => st.notes, (val) => { st.notes = val; }, { key: 'notes', disabled: dis })}
    </section>

    ${'draft_note' in d ? `<section class="panel draft-note"><h3 class="mt-0">Пометка черновика</h3>
      <p class="small">Пока пометка заполнена, версию нельзя утвердить или опубликовать. Её снимают вручную после проверки содержания банком.</p>
      ${b.text('Текст пометки', () => d.draft_note, (val) => { d.draft_note = val; }, { key: 'draft_note', disabled: dis, multiline: true })}
      ${editable ? b.button('Снять пометку черновика…', async () => {
        const ok = await confirmDialog({ title: 'Снять пометку черновика?', body: '<p class="m-0">Снимайте пометку, только если содержание этой версии проверено и подтверждено банком. Изменение вступит в силу после сохранения черновика.</p>', confirmLabel: 'Снять пометку' });
        if (ok) { delete d.draft_note; b.onChange(null, true); }
      }) : ''}</section>` : ''}

    <section class="panel"><h3 class="mt-0">Продукт</h3>
      <div class="form-grid">
        ${b.text('Название продукта', () => d.name, (val) => { d.name = val; }, { key: 'name', disabled: dis, required: true })}
        ${b.text('Сегмент', () => d.segment, (val) => { d.segment = val; }, { key: 'segment', disabled: dis, required: true })}
      </div>
      ${extraTop.length ? `<div class="field"><span class="field-label">Другие поля (сохраняются без изменений)</span>${readOnlyFields(d, extraTop)}</div>` : ''}
    </section>

    ${['approved_facts', 'approved_arguments', 'objections', 'disclaimers'].map(sectionPanel).join('')}

    <section class="panel"><h3 class="mt-0">Ограничения</h3>
      ${b.stringList(KB_SECTION_LABELS.forbidden, () => d.forbidden || [], (list) => { d.forbidden = list; }, { key: 'forbidden', disabled: dis, itemLabel: 'Формулировка' })}
      ${b.stringList(KB_SECTION_LABELS.critical_errors, () => d.critical_errors || [], (list) => { d.critical_errors = list; }, { key: 'critical_errors', disabled: dis, itemLabel: 'Ошибка' })}
    </section>

    <section class="panel"><h3 class="mt-0">История версий</h3><div class="table-wrap"><table class="stack-table">
      <caption class="sr-only">Версии базы знаний</caption>
      <thead><tr><th scope="col">Версия</th><th scope="col">Статус</th><th scope="col">Проверка</th><th scope="col">Автор</th><th scope="col">Утвердил</th><th scope="col">Опубликована</th><th scope="col">Комментарий</th><th scope="col"></th></tr></thead>
      <tbody>${versions.slice().reverse().map((ver) => `<tr${ver.version === st.version ? ' aria-current="true" class="current-row"' : ''}>
        <td data-label="Версия">v${esc(ver.version)}${ver.status === 'published' ? ' <span class="badge success">действующая</span>' : ''}</td>
        <td data-label="Статус">${statusBadge(ver.status)}</td>
        <td data-label="Проверка">${ver.review_blockers ? `<span class="badge error">на проверке: ${esc(ver.review_blockers)}</span>` : 'нет пометок'}</td>
        <td data-label="Автор">${esc(ver.author || '—')}</td><td data-label="Утвердил">${esc(ver.approved_by || '—')}</td>
        <td data-label="Опубликована">${esc(ver.published_at ? fmtDate(ver.published_at) : '—')}</td><td data-label="Комментарий">${esc(ver.notes || '—')}</td>
        <td>${ver.version === st.version ? '<span class="muted small">открыта</span>' : b.button(`Открыть v${ver.version}`, () => openKb(st.productId, ver.version))}</td></tr>`).join('')}</tbody></table></div></section>

    <details class="panel"><summary>Технический вид (JSON, только чтение)</summary><pre class="code-view">${esc(JSON.stringify(d, null, 2))}</pre></details>`;
  refreshKbBlockers();
  if (focusKey) [...root.querySelectorAll('[data-key]')].find((el) => el.dataset.key === focusKey)?.focus();
}

// The blocker summary follows the working copy as it is edited.
function refreshKbBlockers() {
  const st = kbUi.current;
  const blockers = kbBlockers(st.data);
  const anchor = (x) => {
    if (x.section === 'draft_note') return esc(KB_SECTION_LABELS.draft_note);
    const idx = (st.data[x.section] || []).findIndex((e) => e && e.id === x.id && e.needs_review);
    return `${esc(KB_SECTION_LABELS[x.section])} — <a href="#kbe-${esc(x.section)}-${esc(idx)}"><code>${esc(x.id)}</code></a>`;
  };
  $('kb-blockers').innerHTML = blockers.length
    ? `<div class="blocker-box"><b>Утвердить и опубликовать нельзя: требует проверки — ${esc(blockers.length)}</b>
        <ul>${blockers.map((x) => `<li>${anchor(x)}</li>`).join('')}</ul>
        <p class="small m-0">«Требует проверки» — содержание ещё не подтверждено банком и блокирует утверждение и публикацию. «Комментарий комплаенса» — справочная пометка, сама по себе не блокирует.</p></div>`
    : '<p class="small m-0">Пометок «требует проверки» нет.</p>';
}

function kbMessage(html) {
  $('kb-msg').innerHTML = html;
  if (html) $('kb-msg').scrollIntoView({ block: 'nearest' });
}

async function saveKb() {
  const st = kbUi.current;
  const problems = kbProblems(st.data);
  st.invalid.forEach((path) => problems.push(`Поле ${path}: нужно число`));
  if (problems.length) {
    kbMessage(`<div class="error-box"><b>Исправьте перед сохранением:</b><ul>${problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>`);
    return;
  }
  try {
    await api(`/admin/kb/${encodeURIComponent(st.productId)}/versions/${encodeURIComponent(st.version)}`, { method: 'PUT', json: { data: st.data, notes: st.notes } });
    unsaved.set(false);
    kbUi.items = await api('/admin/kb');
    toast(`Черновик v${st.version} сохранён`, 'success');
    await openKb(st.productId, st.version);
  } catch (err) {
    kbMessage(`<div class="error-box">${esc(err.message)}</div>`);
  }
}

async function changeKbStatus(target) {
  const st = kbUi.current;
  if (unsaved.dirty) { kbMessage('<div class="error-box">Сначала сохраните или отмените изменения.</div>'); return; }
  const published = st.product.versions.find((x) => x.status === 'published');
  const ctx = { name: st.data.name || st.productId, version: st.version, status: st.meta.status, publishedVersion: published && published.version };
  if (!(await confirmTransition('kb', ctx, target))) return;
  try {
    await api(`/admin/kb/${encodeURIComponent(st.productId)}/versions/${encodeURIComponent(st.version)}/status`, { method: 'POST', json: { status: target } });
    meta = await api('/admin/meta');
    kbUi.items = await api('/admin/kb');
    toast(`Статус изменён: ${CONTENT_STATUS_TEXT[target]}`, 'success');
    await openKb(st.productId, st.version);
  } catch (err) {
    kbMessage(blockedHtml(err));
  }
}

// ------------------------------------------------------- new version / product

function formDialog(title, fieldsHtml, submitLabel, onSubmit) {
  const dialog = $('dlg');
  $('dlg-body').innerHTML = `<form id="dlg-form"><div class="dialog-head"><h2 id="dlg-title">${esc(title)}</h2></div>${fieldsHtml}
    <div id="dlg-msg" role="alert"></div>
    <div class="dialog-actions"><button type="button" class="secondary" id="dlg-cancel">Отмена</button><button type="submit">${esc(submitLabel)}</button></div></form>`;
  $('dlg-cancel').onclick = () => dialog.close();
  $('dlg-form').onsubmit = async (e) => {
    e.preventDefault();
    try { await onSubmit(); dialog.close(); } catch (err) { $('dlg-msg').innerHTML = `<div class="error-box">${esc(err.message)}</div>`; }
  };
  dialog.showModal();
  dialog.querySelector('input')?.focus();
}

async function newKbVersionDialog(productId, baseVersion) {
  if (!(await unsaved.confirmLeave())) return;
  const product = kbUi.items.find((p) => p.product_id === productId);
  formDialog('Новая версия базы знаний', `
    <p class="small">Новая версия-черновик — копия версии v${esc(baseVersion)} со всеми пометками «требует проверки». Версия v${esc(baseVersion)} не изменится.</p>
    <div class="field"><label for="nv-version">Номер новой версии</label><input type="text" id="nv-version" required value="${esc(nextKbVersion(product.versions))}"/></div>
    <div class="field"><label for="nv-notes">Комментарий к версии</label><input type="text" id="nv-notes"/></div>`, 'Создать черновик', async () => {
    const version = $('nv-version').value.trim();
    if (!version) throw new Error('Укажите номер версии');
    await api(`/admin/kb/${encodeURIComponent(productId)}/versions`, { method: 'POST', json: { version, base_version: baseVersion, notes: $('nv-notes').value || null } });
    kbUi.items = await api('/admin/kb');
    unsaved.set(false);
    await openKb(productId, version);
  });
}

// A new product starts as a draft with exactly what the user typed — no
// template facts, terms or conditions are prefilled.
function newProductDialog() {
  formDialog('Новый продукт', `
    <p class="small">Создаётся черновик базы знаний. Все условия продукта вносит продуктовая команда; редактор ничего не заполняет сам.</p>
    <div class="form-grid">
      <div class="field"><label for="np-id">id продукта (a-z, 0-9, _)</label><input type="text" id="np-id" required pattern="[a-z0-9_]{2,40}"/></div>
      <div class="field"><label for="np-version">Версия</label><input type="text" id="np-version" required value="1.0.0"/></div>
    </div>
    <div class="field"><label for="np-name">Название продукта</label><input type="text" id="np-name" required/></div>
    <div class="field"><label for="np-segment">Сегмент</label><input type="text" id="np-segment" required/></div>
    <fieldset class="list-field"><legend>Первый утверждённый факт (обязательно хотя бы один)</legend>
      <div class="field"><label for="np-fact-id">id факта</label><input type="text" id="np-fact-id" required value="fact_1"/></div>
      <div class="field"><label for="np-fact">Текст факта</label><textarea id="np-fact" required rows="3"></textarea></div>
      <label class="checkbox-row" for="np-review"><input type="checkbox" id="np-review"/> Требует проверки — блокирует утверждение и публикацию</label>
    </fieldset>`, 'Создать черновик', async () => {
    const id = $('np-id').value.trim();
    const fact = { id: $('np-fact-id').value.trim(), text: $('np-fact').value.trim() };
    if ($('np-review').checked) fact.needs_review = true;
    const data = { id, name: $('np-name').value.trim(), segment: $('np-segment').value.trim(), approved_facts: [fact], approved_arguments: [], objections: [], disclaimers: [], forbidden: [], critical_errors: [] };
    const version = $('np-version').value.trim();
    await api(`/admin/kb/${encodeURIComponent(id)}/versions`, { method: 'POST', json: { version, data } });
    meta = await api('/admin/meta');
    kbUi.items = await api('/admin/kb');
    await openKb(id, version);
  });
}
