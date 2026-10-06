// Training page: scenario catalogue + briefing, the live training
// session (text/voice turns, explicit voice states, timer, transcript
// reconciliation after failures) and finish → scoring → result.
//
// Manager-visible data only: the catalogue (/scenarios) and session start
// (POST /sessions) responses, whose hidden-field safety is covered by tests.
// The stored transcript stays the source of truth (Phase 3A).

let me = null;
let scenarios = [];
let sessionId = null;
let currentScenario = null;
let clientName = null;
let busy = false;
let storedTurns = 0;
let mediaRecorder = null;
let recordedChunks = [];
let timerStart = null;
let timerHandle = null;

const $ = (id) => document.getElementById(id);
const chatEl = $('chat');

// Generic description of each level, matching how the AI client is
// instructed to behave (app/prompts.py DIFFICULTY_RULES) — not scenario-specific.
const DIFFICULTY_NOTES = {
  easy: 'Клиент в целом открыт к разговору, возражает мягко и раскрывает потребности после пары уместных вопросов.',
  medium: 'Клиент настроен скептически, приводит несколько возражений и принимает только конкретные ответы.',
  hard: 'Клиент занят или раздражён, часто возражает и сравнивает с конкурентами; скрытые потребности — только на точные вопросы.',
};

// ---------------------------------------------------------------- catalogue

function briefingValue(value) {
  return value === 'варьируется' ? 'определится при старте' : value;
}

function filtersActive() {
  return ['product-filter', 'topic-filter', 'difficulty-filter'].some((id) => $(id).value);
}

function renderCards() {
  if (!scenarios.length) {
    $('cards').innerHTML = stateHtml('empty', 'Пока нет доступных тренировок', 'Сценарии появятся здесь после утверждения и публикации командой обучения.');
    return;
  }
  const product = $('product-filter').value;
  const difficulty = $('difficulty-filter').value;
  const topic = $('topic-filter').value;
  const items = scenarios.filter((s) => (!product || s.product_id === product) && (!difficulty || s.difficulty === difficulty)
    && (!topic || s.topics.some((t) => t.id === topic)));
  $('cards').innerHTML = items.map((s) => `
    <article class="card card-actionable">
      <div class="row"><span class="chip ${esc(s.difficulty)}">${esc(DIFFICULTY[s.difficulty] || s.difficulty)}</span>
        <span class="product">${esc(s.product_name)}</span></div>
      <h3 class="title m-0">${esc(s.title)}</h3>
      <p class="goal m-0">${esc(s.goal)}</p>
      ${s.topics.length ? `<div class="chip-row">${s.topics.map((t) => `<span class="chip topic">${esc(t.name)}</span>`).join('')}</div>` : ''}
      <div class="card-footer"><button type="button" class="secondary" data-brief="${esc(s.id)}">Выбрать</button></div>
    </article>`).join('')
    || `<div>${stateHtml('empty', 'Нет сценариев по выбранным фильтрам', '')}<div class="row justify-center"><button type="button" class="secondary small" id="reset-filters">Сбросить фильтры</button></div></div>`;
}

// ------------------------------------------------------------------ briefing

function openBriefing(scenarioId) {
  const s = scenarios.find((x) => x.id === scenarioId);
  if (!s) {
    toast('Этот сценарий сейчас недоступен.', 'error');
    return;
  }
  const context = s.briefing.filter((b) => b.value);
  $('briefing-body').innerHTML = `
    <div class="dialog-head"><h2 id="briefing-title">${esc(s.title)}</h2>
      <button type="button" class="ghost small" id="briefing-close" aria-label="Закрыть">✕</button></div>
    <div class="briefing-meta"><span>${esc(s.product_name)}</span><span class="chip ${esc(s.difficulty)}">${esc(DIFFICULTY[s.difficulty] || s.difficulty)}</span></div>
    <div class="briefing-section"><h3>Ваша задача</h3><p class="briefing-task m-0">${esc(s.goal)}</p></div>
    ${s.learning_goal ? `<div class="briefing-section"><h3>Чему учит сценарий</h3><p class="m-0">${esc(s.learning_goal)}</p></div>` : ''}
    ${context.length ? `<div class="briefing-section"><h3>Клиент</h3><dl class="facts">${context.map((b) => `<dt>${esc(b.label)}</dt><dd>${esc(briefingValue(b.value))}</dd>`).join('')}</dl></div>` : ''}
    <div class="briefing-section"><h3>Сложность: ${esc(DIFFICULTY[s.difficulty] || s.difficulty)}</h3><p class="difficulty-note m-0">${esc(DIFFICULTY_NOTES[s.difficulty] || '')}</p></div>
    <p class="muted small mt-4 m-0">Каждый раз генерируется новый клиент. Говорите голосом или пишите текстом. Результат не влияет на KPI.</p>
    <div class="dialog-actions"><button type="button" id="briefing-start">Начать тренировку</button><button type="button" class="secondary" id="briefing-cancel">Отмена</button></div>`;
  const dlg = $('briefing-dlg');
  $('briefing-close').addEventListener('click', () => dlg.close());
  $('briefing-cancel').addEventListener('click', () => dlg.close());
  $('briefing-start').addEventListener('click', async (e) => {
    setLoading(e.currentTarget, true);
    const started = await startSession(s);
    if (started) dlg.close();
    else setLoading(e.currentTarget, false);
  });
  dlg.showModal();
  $('briefing-start').focus();
}

// ------------------------------------------------------------ live session

const VOICE_STATES = {
  ready: 'Готово. Удерживайте кнопку микрофона (или пробел на ней) и говорите — или напишите реплику.',
  listening: 'Идёт запись… Отпустите кнопку, чтобы отправить.',
  // One request covers recognition and the client's reply; the browser can't
  // see which step the server is on, so this state names both.
  transcribing: 'Распознаю речь и жду ответ клиента…',
  thinking: 'Клиент думает…',
  speaking: 'Клиент отвечает…',
  audio_unavailable: 'Озвучка недоступна — ответ клиента показан текстом. Можно продолжать.',
  error: 'Реплика не отправлена. Повторите её или напишите текстом.',
  mic_denied: 'Нет доступа к микрофону. Разрешите доступ в браузере или продолжайте текстом.',
  closed: 'Разговор завершён.',
};

function setVoiceState(state) {
  const el = $('voice-state');
  el.dataset.state = state;
  $('voice-state-text').textContent = VOICE_STATES[state];
}

function setBusy(value, state) {
  busy = value;
  $('send-btn').disabled = value;
  $('mic-btn').disabled = value;
  updateFinishButton();
  setVoiceState(value ? (state || 'thinking') : 'ready');
}

function updateFinishButton() {
  const canFinish = !busy && storedTurns > 0;
  $('finish-btn').disabled = !canFinish;
  $('finish-hint').classList.toggle('hidden', storedTurns > 0);
}

function startTimer() {
  timerStart = performance.now();
  const tick = () => {
    const seconds = Math.floor((performance.now() - timerStart) / 1000);
    $('timer-value').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  };
  tick();
  clearInterval(timerHandle);
  timerHandle = setInterval(tick, 1000);
}

function stopTimer() {
  clearInterval(timerHandle);
  timerHandle = null;
}

function showSessionHeader(s) {
  setPageHeader(s.title, `${s.product_name} · ${DIFFICULTY[s.difficulty] || s.difficulty}`);
}

async function startSession(s) {
  try {
    const data = await api('/sessions', { method: 'POST', json: { scenario_id: s.id } });
    sessionId = data.id;
    currentScenario = s;
    const visible = Object.fromEntries(data.briefing.map((b) => [b.label, b.value]));
    clientName = visible['Клиент'] || null;
    $('client-avatar').textContent = clientName ? initials(clientName) : 'AI';
    $('client-name').textContent = clientName || 'AI-клиент';
    $('client-sub').textContent = [visible['Тип бизнеса'], visible['Роль собеседника']].filter(Boolean).join(' · ') || 'Симулированный клиент банка';
    $('context-goal').textContent = data.goal;
    $('context-learning').textContent = data.learning_goal || '';
    $('context-learning-row').classList.toggle('hidden', !data.learning_goal);
    $('context-facts').innerHTML = data.briefing.map((b) => `<dt>${esc(b.label)}</dt><dd>${esc(b.value)}</dd>`).join('');
    showSessionHeader(s);

    $('catalog-view').classList.add('hidden');
    $('session-view').classList.remove('hidden');
    for (const id of ['scoring', 'result', 'after-actions']) $(id).classList.add('hidden');
    for (const id of ['composer', 'session-context', 'finish-row']) $(id).classList.remove('hidden');
    $('text-input').disabled = false;
    $('text-input').value = '';
    chatEl.innerHTML = '';
    storedTurns = 0;
    chatEl.appendChild(turnElement('system', 'Тренировка началась. Поздоровайтесь с клиентом — голосом или текстом.'));
    setBusy(false);
    startTimer();
    window.scrollTo(0, 0);
    $('text-input').focus();
    return true;
  } catch (err) {
    toast('Не удалось начать тренировку: ' + err.message, 'error');
    return false;
  }
}

function addTurn(role, text, opts = {}) {
  const row = turnElement(role, text, { ...opts, clientName });
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;
  return row;
}

// Kept for the shared failure path below: system notes in the transcript.
function addBubble(role, text, meta) {
  return addTurn(role, text, { meta });
}

function afterTurn(data) {
  addTurn('ai_client', data.ai_client_text, { meta: latencyMeta(data.latency_ms), turnIndex: data.ai_client_turn_index });
  storedTurns = data.ai_client_turn_index;
  updateFinishButton();
}

// The stored transcript is the source of truth. After a failed turn the chat
// is redrawn from it, so the screen never shows a line that wasn't saved and
// never misses one that was (e.g. the server saved it but the response was lost).
async function syncChat() {
  try {
    const { turns } = await api(`/sessions/${sessionId}/transcript`);
    renderTranscript(chatEl, turns, clientName);
    storedTurns = turns.length;
    updateFinishButton();
    return true;
  } catch {
    return false;
  }
}

// A turn failed. Show a safe message; if the line wasn't saved, put its text
// back into the input so it can be resent without retyping or re-recording.
async function turnFailed(err, unsentText, hint) {
  const before = storedTurns;
  await syncChat();
  if (storedTurns > before) return;  // it went through after all — nothing to resend
  setVoiceState(err.code === 'stt_unavailable' || err.code === 'dialog_unavailable' || err.code === 'network' ? 'error' : 'ready');
  const note = addBubble('system', err.message + (hint ? ' ' + hint : ''));
  if (unsentText) {
    $('text-input').value = unsentText;
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'secondary small retry';
    retry.textContent = 'Повторить';
    retry.addEventListener('click', () => { note.remove(); sendTurn(); });
    note.appendChild(retry);
  }
}

function playTurnAudio(src) {
  $('audio-player').src = src;
  $('audio-player').play().catch(() => {});
}

async function sendTurn() {
  const text = $('text-input').value.trim();
  if (!text || !sessionId || busy) return;
  $('text-input').value = '';
  const pending = addTurn('manager', text, { meta: 'отправляется…', pending: true });
  setBusy(true, 'thinking');
  try {
    const data = await api(`/sessions/${sessionId}/turns`, { method: 'POST', json: { text } });
    pending.replaceWith(turnElement('manager', text, { turnIndex: data.manager_turn_index, clientName }));
    afterTurn(data);
    setBusy(false);
    playTurnAudio(`/sessions/${sessionId}/turns/${data.ai_client_turn_index}/audio?ts=${Date.now()}`);
  } catch (err) {
    pending.remove();
    setBusy(false);
    await turnFailed(err, text);
  }
}

async function sendVoiceTurn(blob) {
  setBusy(true, 'transcribing');
  const form = new FormData();
  form.append('audio', blob, 'turn.webm');
  try {
    const data = await api(`/sessions/${sessionId}/voice-turn`, { method: 'POST', body: form });
    addTurn('manager', data.manager_text, { turnIndex: data.manager_turn_index });
    afterTurn(data);
    setBusy(false);
    if (data.audio_error) {
      setVoiceState('audio_unavailable');
      addBubble('system', 'Озвучка временно недоступна — прочитайте ответ клиента.');
    } else if (data.ai_client_audio_base64) {
      playTurnAudio(`data:audio/mpeg;base64,${data.ai_client_audio_base64}`);
    }
  } catch (err) {
    setBusy(false);
    const recognised = err.data && err.data.manager_text;
    await turnFailed(err, recognised, recognised ? `Распознано: «${recognised}» — текст в поле ввода, нажмите «Повторить».` : '');
  }
}

async function startRecording() {
  if (!sessionId || busy || (mediaRecorder && mediaRecorder.state === 'recording')) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) recordedChunks.push(e.data); };
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      sendVoiceTurn(new Blob(recordedChunks, { type: 'audio/webm' }));
    };
    mediaRecorder.start();
    $('mic-btn').setAttribute('aria-pressed', 'true');
    $('mic-label').textContent = 'Отпустите, чтобы отправить';
    setVoiceState('listening');
  } catch (err) {
    setVoiceState('mic_denied');
  }
}

function stopRecording() {
  $('mic-btn').setAttribute('aria-pressed', 'false');
  $('mic-label').textContent = 'Удерживать и говорить';
  if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
}

// -------------------------------------------------------- finish → scoring

function setStep(id, state, note) {
  const step = $(id);
  step.dataset.state = state;
  step.querySelector('.step-icon').textContent = state === 'done' ? '✓' : state === 'error' ? '!' : '';
  if (note !== undefined) step.querySelector('.step-note').textContent = note;
}

function confirmFinish() {
  if (busy || storedTurns === 0) return;
  $('finish-dlg').showModal();
  $('finish-cancel').focus();
}

async function finishSession() {
  if (!sessionId) return;
  busy = true;
  stopTimer();
  for (const id of ['composer', 'finish-row']) $(id).classList.add('hidden');
  $('session-context').open = false;
  $('text-input').disabled = true;
  setVoiceState('closed');
  $('scoring').classList.remove('hidden');
  $('scoring-error').classList.add('hidden');
  setStep('step-done', 'done');
  setStep('step-analysis', 'active', 'Проверяем утверждения о продукте по утверждённой базе знаний и оцениваем разговор по критериям. Обычно это занимает до нескольких минут — страницу можно не закрывать.');
  setStep('step-result', 'pending');
  $('scoring').scrollIntoView({ behavior: 'smooth', block: 'start' });
  try {
    // Check current status first so a retry after a dropped connection resumes
    // polling instead of re-POSTing /finish onto a scoring job already in flight.
    let current = null;
    try { current = await api(`/sessions/${sessionId}/score`); } catch { /* fall through */ }
    if (!current || current.status !== 'scoring') {
      await api(`/sessions/${sessionId}/finish`, { method: 'POST' });
    }
    // Fire-and-forget: scoring runs server-side regardless of whether this
    // request survives; the outcome is read by polling /score.
    fetch(`/sessions/${sessionId}/score-run`, { method: 'POST' }).catch(() => {});
    const data = await pollScore();
    setStep('step-analysis', 'done', '');
    setStep('step-result', 'done');
    const sid = sessionId;
    await renderResult($('result'), data, {
      onDispute: (comment) => api(`/sessions/${sid}/dispute`, { method: 'POST', json: { comment } }),
    });
    $('scoring').classList.add('hidden');
    $('result').classList.remove('hidden');
    $('after-actions').classList.remove('hidden');
    busy = false;
    $('result').focus();
    $('result').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    setStep('step-analysis', 'error', 'Оценка не завершилась.');
    $('scoring-error-text').textContent = err.message;
    $('scoring-error').classList.remove('hidden');
    busy = false;
  }
}

async function pollScore() {
  // The server caps a scoring run at ~270s; past this the run is lost, not slow.
  const deadline = Date.now() + 6 * 60 * 1000;
  let networkRetries = 0;
  while (true) {
    if (Date.now() > deadline) throw new Error('Оценка заняла слишком много времени. Нажмите «Повторить оценку».');
    let data;
    try {
      data = await api(`/sessions/${sessionId}/score`);
      networkRetries = 0;
    } catch (err) {
      networkRetries += 1;
      if (networkRetries > 5) throw err;
      await new Promise((r) => setTimeout(r, 3000));
      continue;
    }
    if (data.status === 'finished') return data;
    // The server's safe message names the old button; this page offers "Повторить оценку".
    if (data.status === 'finish_error') throw new Error(data.code === 'scoring_unavailable' ? 'Оценка временно недоступна. Нажмите «Повторить оценку» — разговор сохранён.' : (data.detail || 'Оценка временно недоступна.'));
    await new Promise((r) => setTimeout(r, 3000));
  }
}

function backToCatalog() {
  sessionId = null;
  currentScenario = null;
  stopTimer();
  $('session-view').classList.add('hidden');
  $('catalog-view').classList.remove('hidden');
  setPageHeader('Тренировка', 'Каждый раз генерируется новый клиент. Результаты тренировок не влияют на KPI.');
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ wiring

document.addEventListener('click', (e) => {
  const brief = e.target.closest('[data-brief]');
  if (brief) openBriefing(brief.dataset.brief);
  if (e.target.id === 'reset-filters') {
    ['product-filter', 'topic-filter', 'difficulty-filter'].forEach((id) => { $(id).value = ''; });
    renderCards();
  }
});
$('product-filter').addEventListener('change', renderCards);
$('difficulty-filter').addEventListener('change', renderCards);
$('topic-filter').addEventListener('change', renderCards);
$('send-btn').addEventListener('click', sendTurn);
$('text-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendTurn(); });
const audioPlayer = $('audio-player');
audioPlayer.addEventListener('playing', () => { if (!busy) setVoiceState('speaking'); });
audioPlayer.addEventListener('ended', () => { if ($('voice-state').dataset.state === 'speaking') setVoiceState('ready'); });
audioPlayer.addEventListener('error', () => {
  if (audioPlayer.getAttribute('src') && sessionId) {
    setVoiceState('audio_unavailable');
    addBubble('system', 'Озвучка временно недоступна — прочитайте ответ клиента.');
  }
});
$('finish-btn').addEventListener('click', confirmFinish);
$('finish-confirm').addEventListener('click', () => { $('finish-dlg').close(); finishSession(); });
$('finish-cancel').addEventListener('click', () => $('finish-dlg').close());
$('scoring-retry').addEventListener('click', finishSession);
$('scoring-back').addEventListener('click', backToCatalog);
$('repeat-btn').addEventListener('click', () => openBriefing(currentScenario.id));
$('back-btn').addEventListener('click', backToCatalog);
const mic = $('mic-btn');
mic.addEventListener('mousedown', startRecording);
mic.addEventListener('mouseup', stopRecording);
mic.addEventListener('mouseleave', stopRecording);
mic.addEventListener('touchstart', (e) => { e.preventDefault(); startRecording(); });
mic.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });
mic.addEventListener('keydown', (e) => { if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); startRecording(); } });
mic.addEventListener('keyup', (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); stopRecording(); } });

(async () => {
  me = await initPage('train');
  if (!me.can_train) {
    location.href = me.can_dashboard ? '/dashboard' : '/admin';
    return;
  }
  try {
    scenarios = await api('/scenarios');
  } catch (err) {
    $('cards').innerHTML = stateHtml('error', 'Не удалось загрузить тренировки', err.message);
    return;
  }
  const products = [...new Map(scenarios.map((s) => [s.product_id, s.product_name])).entries()];
  $('product-filter').innerHTML += products.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join('');
  const topics = [...new Map(scenarios.flatMap((s) => s.topics).map((t) => [t.id, t.name])).entries()];
  $('topic-filter').innerHTML += topics.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join('');
  renderCards();
  const repeat = new URLSearchParams(location.search).get('repeat');
  if (repeat) openBriefing(repeat);
})();
