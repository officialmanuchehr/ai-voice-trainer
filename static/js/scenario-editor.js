// Scenario list and structured editor (Phase 7). Edits a working copy of the
// stored version; untouched fields (unknown profile keys, internal config,
// order of lists) are sent back exactly as loaded. Saving goes through the
// existing PUT/POST endpoints; the server validates and versions.

const scenarioUi = { items: [], kb: [], current: null };

function statusBadge(status) {
  const cls = { draft: 'plain', approved: 'warning', published: 'success', archived: 'plain' }[status] || 'plain';
  return `<span class="badge ${esc(cls)}">${esc(CONTENT_STATUS_TEXT[status] || status)}</span>`;
}

function productName(id) {
  const p = meta.products.find((x) => x.id === id);
  return p ? p.name : id;
}

// ------------------------------------------------------------------ list

async function loadScenarios() {
  showScenarioList();
  [scenarioUi.items, scenarioUi.kb] = await Promise.all([api('/admin/scenarios'), api('/admin/kb')]);
  const rows = scenarioUi.items.map((s) => {
    const latest = s.versions[s.versions.length - 1];
    return `<tr>
      <td data-label="Сценарий"><div>${esc(s.title)}</div><div class="muted small">${esc(s.id)}</div></td>
      <td data-label="Продукт">${esc(productName(s.product_id))}</td>
      <td data-label="Сложность">${esc(DIFFICULTY[s.difficulty] || s.difficulty)}</td>
      <td data-label="Опубликована">${s.published_version ? `v${esc(s.published_version)}` : '<span class="muted">нет</span>'}</td>
      <td data-label="Последняя версия">${latest ? `v${esc(latest.version)} ${statusBadge(latest.status)}<div class="muted small">${esc(latest.author || '—')} · ${esc(fmtDate(latest.updated_at || latest.created_at))}</div>` : '—'}</td>
      <td data-label="Действия"><button type="button" class="secondary small" data-open-scn="${esc(s.id)}" data-ver="${esc(latest ? latest.version : '')}">Открыть</button></td></tr>`;
  }).join('');
  $('scenario-table').innerHTML = rows
    ? `<caption class="sr-only">Сценарии</caption><thead><tr><th scope="col">Сценарий</th><th scope="col">Продукт</th><th scope="col">Сложность</th><th scope="col">Опубликована</th><th scope="col">Последняя версия</th><th scope="col">Действия</th></tr></thead><tbody>${rows}</tbody>`
    : `<tbody><tr><td>${stateHtml('empty', 'Сценариев пока нет', meta.permissions.scenario_edit ? 'Создайте первый сценарий.' : '')}</td></tr></tbody>`;
}

function showScenarioList() {
  $('scenario-list').classList.remove('hidden');
  $('scenario-editor').classList.add('hidden');
}

// ---------------------------------------------------------------- editor

function publishedKbInfo(productId) {
  const product = scenarioUi.kb.find((p) => p.product_id === productId);
  const published = product && product.versions.find((v) => v.status === 'published');
  if (!published) return '<p class="note-box m-0">У продукта нет опубликованной базы знаний — сценарий нельзя будет опубликовать.</p>';
  if (published.review_blockers) return `<p class="note-box m-0">Опубликованная база знаний v${esc(published.version)} содержит непроверенные записи (${esc(published.review_blockers)}) — публикация сценария будет заблокирована.</p>`;
  return `<p class="muted small m-0">Опубликованная база знаний продукта: v${esc(published.version)}.</p>`;
}

const scenarioPerms = () => ({ edit: meta.permissions.scenario_edit, approve: meta.permissions.scenario_approve, publish: meta.permissions.scenario_publish });

// mode: 'view' (stored version), 'draft' (editing a draft), 'new-version'
// (editing a copy of a non-draft version), 'new' (new scenario).
async function openScenario(id, version, mode) {
  if (!(await unsaved.confirmLeave())) return;
  let v;
  if (id) v = await api(`/admin/scenarios/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`);
  const item = id ? scenarioUi.items.find((s) => s.id === id) : null;
  const perms = scenarioPerms();
  const resolved = !id ? 'new' : mode || (v.status === 'draft' && perms.edit ? 'draft' : 'view');
  const data = id ? deepClone(v.data) : {
    title: '', product_id: meta.products[0] ? meta.products[0].id : '', difficulty: 'medium', rubric_id: meta.rubrics[0].id,
    goal: '', topics: [], client_profile: { variants: {} }, config: { learning_goal: '', criteria_weights: {}, good_examples: [], feedback_hints: [] },
  };
  data.client_profile = data.client_profile || {};
  data.config = data.config || {};
  scenarioUi.current = { id, version: v ? v.version : null, meta: v, item, mode: resolved, data };
  unsaved.set(false);
  $('scenario-list').classList.add('hidden');
  $('scenario-editor').classList.remove('hidden');
  renderScenarioEditor();
  $('scenario-editor').querySelector('h2').focus();
}

let scenarioBinder = null;
function renderScenarioEditor(focusKey) {
  const root = $('scenario-editor');
  if (!scenarioBinder) scenarioBinder = new FormBinder(root, (binding, structural, key) => {
    unsaved.set(true);
    $('scn-dirty').textContent = 'Есть несохранённые изменения';
    if (structural) renderScenarioEditor(key);
  });
  const b = scenarioBinder;
  b.reset();
  const st = scenarioUi.current;
  const d = st.data;
  const editable = st.mode !== 'view';
  const dis = !editable;
  const perms = scenarioPerms();
  const versions = st.item ? st.item.versions : [];
  const latest = versions[versions.length - 1];
  const newerDraft = latest && latest.status === 'draft' && latest.version !== st.version ? latest : null;

  let banner;
  if (st.mode === 'new') banner = 'Новый сценарий. При сохранении появится черновик v1.';
  else if (st.mode === 'draft') banner = `Черновик v${st.version}. Изменения сохраняются в эту версию; опубликованные версии не меняются.`;
  else if (st.mode === 'new-version') banner = `Новая версия на основе v${st.version}. Версия v${st.version} (${CONTENT_STATUS_TEXT[st.meta.status]}) не изменится — при сохранении появится черновик v${latest.version + 1}.`;
  else banner = `Версия v${st.version} · ${CONTENT_STATUS_TEXT[st.meta.status] || st.meta.status}. ${st.meta.status === 'draft' ? 'Только просмотр для вашей роли.' : 'Утверждённые, опубликованные и архивные версии не редактируются.'}`;

  const rubric = meta.rubrics.find((r) => r.id === d.rubric_id) || meta.rubrics[0];
  const weights = () => { d.config.criteria_weights = d.config.criteria_weights || {}; return d.config.criteria_weights; };

  const profile = d.client_profile;
  const variants = () => { profile.variants = profile.variants || {}; return profile.variants; };
  const rows = profileRows(profile, meta.profile_fields);
  const fieldBlock = (row) => {
    const parts = [];
    const base = profile[row.key];
    const baseIsList = Array.isArray(base);
    const editableBase = row.hasBase && (typeof base === 'string' || (baseIsList && base.every((x) => typeof x === 'string')));
    if (row.hasBase) {
      if (!editableBase) parts.push(`<div class="field"><span class="field-label">Значение (только просмотр)</span><code>${esc(JSON.stringify(base))}</code></div>`);
      else if (baseIsList) parts.push(b.stringList('Значение — список', () => profile[row.key], (list) => { profile[row.key] = list; }, { key: `p.${row.key}`, disabled: dis, itemLabel: 'Пункт' }));
      else parts.push(b.text('Значение', () => profile[row.key], (val) => { profile[row.key] = val; }, { key: `p.${row.key}`, disabled: dis, multiline: true }));
      if (editable && row.hasVariants) parts.push(b.button('Убрать базовое значение', () => { delete profile[row.key]; b.onChange(null, true); }));
    } else if (editable) {
      parts.push(b.button('Добавить базовое значение', () => { profile[row.key] = row.list ? [''] : ''; b.onChange(null, true, `p.${row.key}`); }));
    }
    if (row.hasVariants) {
      const options = variants()[row.key];
      if (Array.isArray(options) && options.every((x) => typeof x === 'string')) {
        parts.push(b.stringList('Варианты — для каждой тренировки выбирается один', () => variants()[row.key], (list) => { if (list.length) variants()[row.key] = list; else delete variants()[row.key]; }, { key: `v.${row.key}`, disabled: dis, itemLabel: 'Вариант', addLabel: 'Добавить вариант' }));
      } else {
        parts.push(`<div class="field"><span class="field-label">Варианты (только просмотр)</span><code>${esc(JSON.stringify(options))}</code></div>`);
      }
    } else if (editable && !row.list) {
      parts.push(b.button('Добавить варианты', () => { variants()[row.key] = ['']; b.onChange(null, true, `v.${row.key}.0`); }));
    }
    const remove = editable ? b.button('Удалить поле', () => { delete profile[row.key]; if (profile.variants) delete profile.variants[row.key]; b.onChange(null, true); }, { aria: `Удалить поле ${row.label}` }) : '';
    return `<div class="profile-field">
      <div class="row"><b>${esc(row.label)}</b><code class="muted small">${esc(row.key)}</code>
        ${row.briefing ? '<span class="badge info">видит менеджер</span>' : '<span class="badge plain">скрыто от менеджера</span>'}
        ${row.known ? '' : '<span class="badge warning">поле не используется AI-клиентом</span>'}<span class="spacer"></span>${remove}</div>
      ${parts.join('')}</div>`;
  };
  const visibleRows = rows.filter((r) => r.briefing).map(fieldBlock).join('');
  const hiddenRows = rows.filter((r) => !r.briefing).map(fieldBlock).join('');
  const missing = meta.profile_fields.filter((f) => !rows.some((r) => r.key === f.id));
  let addFieldChoice = missing.length ? missing[0].id : '';
  const addField = editable && missing.length ? `<div class="row mt-2">${b.select('Добавить поле профиля', missing.map((f) => [f.id, `${f.label}${f.briefing ? ' (видит менеджер)' : ''}`]), () => addFieldChoice, (val) => { addFieldChoice = val; }, { key: 'add-field' })}
      ${b.button('Добавить поле', () => { const f = meta.profile_fields.find((x) => x.id === addFieldChoice); if (!f) return; profile[f.id] = f.list ? [''] : ''; b.onChange(null, true, `p.${f.id}`); })}</div>` : '';

  const topics = Object.entries(meta.topics).map(([tid, name]) => b.checkbox(name, () => (d.topics || []).includes(tid), (on) => {
    d.topics = d.topics || [];
    if (on && !d.topics.includes(tid)) d.topics.push(tid);
    if (!on) d.topics = d.topics.filter((t) => t !== tid);
  }, { key: `topic.${tid}`, disabled: dis })).join('');

  const weightInputs = rubric.criteria.map((c) => b.text(`${c.name} (по умолчанию ${c.weight})`, () => (c.id in weights() ? weights()[c.id] : ''), (val) => {
    if (val === '') delete weights()[c.id];
    else weights()[c.id] = Number.isNaN(Number(val)) ? val : Number(val);
  }, { key: `w.${c.id}`, disabled: dis, type: 'number' })).join('');

  const actions = [];
  if (editable) actions.push(b.button(st.mode === 'new' ? 'Создать черновик' : st.mode === 'draft' ? 'Сохранить черновик' : `Сохранить как черновик v${latest.version + 1}`, saveScenario, { cls: '' }));
  if (st.mode === 'new-version') actions.push(b.button('Отменить', () => openScenario(st.id, st.version, 'view')));
  if (st.mode === 'view' && perms.edit && st.meta.status !== 'draft') {
    if (newerDraft) actions.push(`<span class="muted small">Уже есть черновик v${esc(newerDraft.version)}.</span>${b.button(`Открыть черновик v${newerDraft.version}`, () => openScenario(st.id, newerDraft.version))}`);
    else actions.push(b.button(`Создать новую версию на основе v${st.version}`, async () => { await openScenario(st.id, st.version, 'new-version'); }));
  }
  if (st.id && (st.mode === 'view' || st.mode === 'draft')) {
    allowedTransitions(st.meta.status, perms).forEach(([to, label]) => actions.push(b.button(label, () => changeScenarioStatus(to), { cls: to === 'archived' ? 'secondary small danger-text' : 'secondary small' })));
  }

  const history = versions.length ? `<section class="panel"><h3 class="mt-0">История версий</h3><div class="table-wrap"><table class="stack-table">
    <caption class="sr-only">Версии сценария</caption>
    <thead><tr><th scope="col">Версия</th><th scope="col">Статус</th><th scope="col">Автор</th><th scope="col">Изменена</th><th scope="col">Утвердил</th><th scope="col">Опубликована</th><th scope="col"></th></tr></thead>
    <tbody>${versions.slice().reverse().map((ver) => `<tr${ver.version === st.version ? ' aria-current="true" class="current-row"' : ''}>
      <td data-label="Версия">v${esc(ver.version)}${st.item.published_version === ver.version ? ' <span class="badge success">действующая</span>' : ''}</td>
      <td data-label="Статус">${statusBadge(ver.status)}</td><td data-label="Автор">${esc(ver.author || '—')}</td>
      <td data-label="Изменена">${esc(fmtDate(ver.updated_at || ver.created_at))}</td><td data-label="Утвердил">${esc(ver.approved_by || '—')}</td>
      <td data-label="Опубликована">${esc(ver.published_at ? fmtDate(ver.published_at) : '—')}</td>
      <td>${ver.version === st.version ? '<span class="muted small">открыта</span>' : b.button(`Открыть v${ver.version}`, () => openScenario(st.id, ver.version))}</td></tr>`).join('')}</tbody></table></div></section>` : '';

  root.innerHTML = `
    <div class="row mb-2">${b.button('← Все сценарии', async () => { if (await unsaved.confirmLeave()) { unsaved.set(false); loadScenarios(); } }, { cls: 'ghost small' })}</div>
    <section class="panel">
      <div class="row"><h2 class="m-0" tabindex="-1">${esc(d.title || 'Новый сценарий')}${st.version ? ` · v${esc(st.version)}` : ''}</h2>${st.meta ? statusBadge(st.meta.status) : ''}</div>
      ${st.meta ? `<p class="muted small">Автор: ${esc(st.meta.author || '—')} · изменено ${esc(fmtDate(st.meta.updated_at || st.meta.created_at))}${st.meta.approved_by ? ' · утвердил ' + esc(st.meta.approved_by) : ''}${st.meta.published_at ? ' · опубликовано ' + esc(fmtDate(st.meta.published_at)) : ''}</p>` : ''}
      <p class="note-box">${esc(banner)}</p>
      <div id="scn-msg" role="alert"></div>
      <div class="row editor-actions">${actions.join('')}<span class="muted small" id="scn-dirty" role="status"></span></div>
    </section>

    <section class="panel"><h3 class="mt-0">Основное</h3>
      ${b.text('Название (видит менеджер)', () => d.title, (val) => { d.title = val; }, { key: 'title', disabled: dis, required: true })}
      <div class="form-grid">
        ${b.select('Продукт', meta.products.map((p) => [p.id, p.name]), () => d.product_id, (val) => { d.product_id = val; b.onChange(null, true); }, { key: 'product', disabled: dis })}
        ${b.select('Сложность', meta.difficulties.map((x) => [x, DIFFICULTY[x] || x]), () => d.difficulty, (val) => { d.difficulty = val; }, { key: 'difficulty', disabled: dis })}
        ${b.select('Рубрика оценки', meta.rubrics.map((r) => [r.id, r.title]), () => d.rubric_id, (val) => { d.rubric_id = val; b.onChange(null, true); }, { key: 'rubric', disabled: dis })}
      </div>
      ${publishedKbInfo(d.product_id)}
      <fieldset class="list-field mt-2"><legend>Темы тренировки (видит менеджер в каталоге)</legend><div class="weights">${topics}</div></fieldset>
    </section>

    <section class="panel"><h3 class="mt-0">Видит менеджер</h3>
      <p class="muted small">Показывается в каталоге и брифинге перед тренировкой. Продуктовые условия сюда не пишутся — только в базу знаний.</p>
      ${b.text('Цель разговора', () => d.goal, (val) => { d.goal = val; }, { key: 'goal', disabled: dis, multiline: true, required: true })}
      ${b.text('Чему учит сценарий', () => d.config.learning_goal, (val) => { d.config.learning_goal = val; }, { key: 'learning_goal', disabled: dis, multiline: true })}
      ${visibleRows || '<p class="muted small">Поля брифинга не заполнены.</p>'}
    </section>

    <section class="panel"><h3 class="mt-0">Скрыто от менеджера — профиль AI-клиента</h3>
      <p class="muted small">Эти поля знает только AI-клиент; менеджер выясняет их в разговоре. Если у поля есть варианты, для каждой тренировки выбирается один из них.</p>
      ${hiddenRows || '<p class="muted small">Скрытые поля не заполнены.</p>'}
      ${addField}
    </section>

    <section class="panel"><h3 class="mt-0">Обучение и оценка (внутреннее)</h3>
      <p class="muted small">Не показывается менеджеру до оценки. Пустой вес — значение рубрики по умолчанию; 0 — критерий не учитывается.</p>
      <div class="weights">${weightInputs}</div>
      ${b.stringList('Примеры хороших ответов', () => (d.config.good_examples = d.config.good_examples || []), (list) => { d.config.good_examples = list; }, { key: 'good', disabled: dis, itemLabel: 'Пример' })}
      ${b.stringList('Подсказки для оценщика', () => (d.config.feedback_hints = d.config.feedback_hints || []), (list) => { d.config.feedback_hints = list; }, { key: 'hints', disabled: dis, itemLabel: 'Подсказка' })}
    </section>

    ${history}
    <details class="panel"><summary>Технический вид (JSON, только чтение)</summary><pre class="code-view">${esc(JSON.stringify(d, null, 2))}</pre></details>`;
  if (focusKey) [...root.querySelectorAll('[data-key]')].find((el) => el.dataset.key === focusKey)?.focus();
}

function scenarioMessage(html) {
  $('scn-msg').innerHTML = html;
  if (html) $('scn-msg').scrollIntoView({ block: 'nearest' });
}

async function saveScenario() {
  const st = scenarioUi.current;
  const problems = scenarioProblems(st.data);
  if (problems.length) {
    scenarioMessage(`<div class="error-box"><b>Исправьте перед сохранением:</b><ul>${problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>`);
    return;
  }
  try {
    const res = st.mode === 'new'
      ? await api('/admin/scenarios', { method: 'POST', json: { data: st.data } })
      : await api(`/admin/scenarios/${encodeURIComponent(st.id)}`, { method: 'PUT', json: { data: st.data, base_version: st.version } });
    unsaved.set(false);
    scenarioUi.items = await api('/admin/scenarios');
    toast(`Сохранено: черновик v${res.version}`, 'success');
    await openScenario(res.id, res.version);
  } catch (err) {
    scenarioMessage(`<div class="error-box">${esc(err.message)}</div>`);
  }
}

function transitionText(target, kind, ctx) {
  const name = esc(ctx.name);
  const ver = esc(ctx.version);
  const current = ctx.publishedVersion && String(ctx.publishedVersion) !== String(ctx.version) ? ` Текущая опубликованная версия v${esc(ctx.publishedVersion)} будет переведена в архив.` : '';
  const scenario = kind === 'scenario';
  return {
    approved: `<p>Версия v${ver} ${scenario ? 'сценария' : 'базы знаний'} «${name}» будет утверждена. Публикация — отдельный шаг.</p>`,
    published: scenario
      ? `<p>Версия v${ver} сценария «${name}» станет доступна менеджерам для новых тренировок.${current}</p><p>Прошедшие тренировки остаются привязаны к своим версиям.</p>`
      : `<p>Версия v${ver} станет действующей базой знаний продукта «${name}»: по ней AI-клиент и оценщик будут работать в новых тренировках.${current}</p><p>Прошедшие тренировки остаются привязаны к своей версии.</p>`,
    draft: `<p>Версия v${ver} вернётся в черновик и снова станет редактируемой.</p>`,
    archived: ctx.status === 'published'
      ? (scenario
        ? `<p>Сценарий «${name}» перестанет быть доступен для новых тренировок. Вернуть версию из архива нельзя.</p>`
        : `<p>У продукта «${name}» не останется опубликованной базы знаний — новые тренировки по его сценариям начать будет нельзя, пока не опубликована другая версия. Вернуть версию из архива нельзя.</p>`)
      : `<p>Версия v${ver} будет перемещена в архив. Вернуть её из архива нельзя.</p>`,
  }[target];
}

async function confirmTransition(kind, ctx, target) {
  return confirmDialog({
    title: `${kind === 'scenario' ? 'Сценарий' : 'База знаний'} · v${ctx.version} → ${CONTENT_STATUS_TEXT[target]}`,
    body: `<p class="muted small">${kind === 'scenario' ? 'Сценарий' : 'Продукт'}: «${esc(ctx.name)}» · версия v${esc(ctx.version)} · ${esc(CONTENT_STATUS_TEXT[ctx.status])} → ${esc(CONTENT_STATUS_TEXT[target])}</p>${transitionText(target, kind, ctx)}`,
    confirmLabel: { approved: 'Утвердить', published: 'Опубликовать', draft: 'Вернуть в черновик', archived: 'В архив' }[target],
    danger: target === 'archived',
  });
}

// A refused transition: blockers are listed exactly as the server returned them.
function blockedHtml(err) {
  const items = (err.data && err.data.unreviewed) || [];
  const list = items.length ? `<ul>${items.map((x) => `<li>${esc(KB_SECTION_LABELS[x.section] || x.section)}${x.id ? ` — <code>${esc(x.id)}</code>` : ''}</li>`).join('')}</ul>` : '';
  const hint = err.code === 'kb_not_clean' ? '<p class="m-0">Сначала опубликуйте проверенную версию базы знаний этого продукта.</p>' : '';
  return `<div class="error-box" role="alert"><b>Действие не выполнено.</b> ${esc(err.message)}${list}${hint}</div>`;
}

async function changeScenarioStatus(target) {
  const st = scenarioUi.current;
  if (unsaved.dirty) { scenarioMessage('<div class="error-box">Сначала сохраните или отмените изменения.</div>'); return; }
  const ctx = { name: st.data.title, version: st.version, status: st.meta.status, publishedVersion: st.item.published_version };
  if (!(await confirmTransition('scenario', ctx, target))) return;
  try {
    await api(`/admin/scenarios/${encodeURIComponent(st.id)}/versions/${encodeURIComponent(st.version)}/status`, { method: 'POST', json: { status: target } });
    scenarioUi.items = await api('/admin/scenarios');
    toast(`Статус изменён: ${CONTENT_STATUS_TEXT[target]}`, 'success');
    await openScenario(st.id, st.version);
  } catch (err) {
    scenarioMessage(blockedHtml(err));
  }
}
