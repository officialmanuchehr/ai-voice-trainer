// Training page: scenario catalogue, history, and the live training session
// (text/voice turns, transcript reconciliation after failures, scoring).

let me = null;
let scenarios = [];
let sessionId = null;
let currentScenarioId = null;
let busy = false;
let storedTurns = 0;
let mediaRecorder = null;
let recordedChunks = [];

const $ = (id) => document.getElementById(id);
const chatEl = $('chat');

function addBubble(role, text, meta) {
  const div = document.createElement('div');
  div.className = 'bubble ' + role;
  div.textContent = text;
  if (meta) {
    const m = document.createElement('span');
    m.className = 'meta';
    m.textContent = meta;
    div.appendChild(m);
  }
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function setBusy(value, message) {
  busy = value;
  $('send-btn').disabled = value;
  $('mic-btn').disabled = value;
  $('finish-btn').disabled = value;
  $('processing').textContent = message || 'Клиент думает…';
  $('processing').classList.toggle('hidden', !value);
}

function renderCards() {
  const product = $('product-filter').value;
  const difficulty = $('difficulty-filter').value;
  const topic = $('topic-filter').value;
  const items = scenarios.filter((s) => (!product || s.product_id === product) && (!difficulty || s.difficulty === difficulty)
    && (!topic || s.topics.some((t) => t.id === topic)));
  $('cards').innerHTML = items.map((s) => `
    <div class="card">
      <div class="row"><span class="chip ${esc(s.difficulty)}">${esc(DIFFICULTY[s.difficulty] || s.difficulty)}</span>
        <span class="muted small">${esc(s.product_name)}</span></div>
      <div class="title">${esc(s.title)}</div>
      <div class="small">${esc(s.goal)}</div>
      ${s.learning_goal ? `<div class="small muted">Учебная цель: ${esc(s.learning_goal)}</div>` : ''}
      ${s.topics.length ? `<div class="row">${s.topics.map((t) => `<span class="chip topic">${esc(t.name)}</span>`).join('')}</div>` : ''}
      <div class="spacer"></div>
      <button data-start="${esc(s.id)}">Начать</button>
    </div>`).join('') || '<p class="muted">Нет опубликованных сценариев по этому фильтру.</p>';
}

async function loadHistory() {
  const rows = await api('/me/sessions');
  $('history').innerHTML = rows.length ? `
    <tr><th>Дата</th><th>Сценарий</th><th>Статус</th><th class="num">Балл</th><th></th></tr>
    ${rows.map((r) => `<tr>
      <td>${fmtDate(r.started_at)}</td>
      <td>${esc(r.title)}<div class="muted small">${esc(r.product_name || '')} · ${esc(DIFFICULTY[r.difficulty] || '')}</div></td>
      <td>${esc(SESSION_STATUS[r.status] || r.status)}${r.critical_errors ? ` <span class="flag-text small">⚠ крит. ошибок: ${r.critical_errors}</span>` : ''}${r.disputed ? ' <span class="chip">оспорено</span>' : ''}</td>
      <td class="num">${r.total ?? '—'}</td>
      <td class="row justify-end">
        ${r.status === 'finished' ? `<a class="btn secondary small" href="/session?id=${encodeURIComponent(r.id)}">Разбор</a>` : ''}
        ${r.scenario_available ? `<button class="small" data-start="${esc(r.scenario_id)}">Повторить</button>` : ''}
      </td></tr>`).join('')}` : '<tr><td class="muted">Вы ещё не проходили тренировок.</td></tr>';
}

async function startSession(scenarioId) {
  try {
    const data = await api('/sessions', { method: 'POST', json: { scenario_id: scenarioId } });
    sessionId = data.id;
    currentScenarioId = scenarioId;
    $('catalog-view').classList.add('hidden');
    $('session-view').classList.remove('hidden');
    $('result').classList.add('hidden');
    $('after-actions').classList.add('hidden');
    $('text-input').disabled = false;
    setBusy(false);
    $('context').innerHTML = `
      <div class="row"><span class="chip ${esc(data.difficulty)}">${esc(DIFFICULTY[data.difficulty])}</span><strong>${esc(data.title)}</strong></div>
      <p class="my-1"><span class="muted">Цель разговора:</span> ${esc(data.goal)}</p>
      ${data.learning_goal ? `<p class="small my-1"><span class="muted">Учебная цель:</span> ${esc(data.learning_goal)}</p>` : ''}
      ${data.briefing.map((b) => `<div class="small"><span class="muted">${esc(b.label)}:</span> ${esc(b.value)}</div>`).join('')}`;
    chatEl.innerHTML = '';
    storedTurns = 0;
    addBubble('system', 'Сессия начата. Начните разговор — голосом или текстом.');
    window.scrollTo(0, 0);
    $('text-input').focus();
  } catch (err) {
    toast('Не удалось начать сессию: ' + err.message, 'error');
  }
}

function latencyMeta(ms) {
  return ms != null ? `ответ ${(ms / 1000).toFixed(1)} с` : null;
}

function afterTurn(data) {
  addBubble('ai_client', data.ai_client_text, latencyMeta(data.latency_ms));
  storedTurns = data.ai_client_turn_index;
}

// The stored transcript is the source of truth. After a failed turn the chat
// is redrawn from it, so the screen never shows a line that wasn't saved and
// never misses one that was (e.g. the server saved it but the response was lost).
async function syncChat() {
  try {
    const { turns } = await api(`/sessions/${sessionId}/transcript`);
    chatEl.innerHTML = '';
    for (const t of turns) addBubble(t.role, t.text, latencyMeta(t.latency_ms));
    storedTurns = turns.length;
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
  const note = addBubble('system', err.message + (hint ? ' ' + hint : ''));
  if (unsentText) {
    $('text-input').value = unsentText;
    const retry = document.createElement('button');
    retry.className = 'secondary small';
    retry.textContent = 'Повторить';
    retry.classList.add('retry');
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
  const pending = addBubble('manager', text, 'отправляется…');
  setBusy(true);
  try {
    const data = await api(`/sessions/${sessionId}/turns`, { method: 'POST', json: { text } });
    pending.querySelector('.meta').remove();
    afterTurn(data);
    playTurnAudio(`/sessions/${sessionId}/turns/${data.ai_client_turn_index}/audio?ts=${Date.now()}`);
  } catch (err) {
    pending.remove();
    await turnFailed(err, text);
  } finally {
    setBusy(false);
  }
}

async function sendVoiceTurn(blob) {
  const placeholder = addBubble('system', 'Распознаю речь…');
  setBusy(true);
  const form = new FormData();
  form.append('audio', blob, 'turn.webm');
  try {
    const data = await api(`/sessions/${sessionId}/voice-turn`, { method: 'POST', body: form });
    placeholder.remove();
    addBubble('manager', data.manager_text);
    afterTurn(data);
    if (data.audio_error) addBubble('system', 'Озвучка временно недоступна — прочитайте ответ клиента.');
    else if (data.ai_client_audio_base64) playTurnAudio(`data:audio/mpeg;base64,${data.ai_client_audio_base64}`);
  } catch (err) {
    placeholder.remove();
    const recognised = err.data && err.data.manager_text;
    await turnFailed(err, recognised, recognised ? `Распознано: «${recognised}» — текст в поле ввода, нажмите «Повторить».` : '');
  } finally {
    setBusy(false);
  }
}

async function startRecording() {
  if (!sessionId || busy) return;
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
    $('mic-btn').textContent = '🔴 Запись… отпустите, чтобы отправить';
  } catch (err) {
    addBubble('system', 'Нет доступа к микрофону: ' + err.message);
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
  $('mic-btn').textContent = '🎤 Удерживать и говорить';
}

async function finishSession() {
  if (!sessionId) return;
  setBusy(true, 'Оцениваю разговор — это может занять пару минут, не закрывайте страницу…');
  $('text-input').disabled = true;
  try {
    // Check current status first so a retry after a dropped connection resumes
    // polling instead of re-POSTing /finish onto a scoring job already in flight.
    let current = null;
    try { current = await api(`/sessions/${sessionId}/score`); } catch { /* fall through */ }
    if (!current || current.status !== 'scoring') {
      await api(`/sessions/${sessionId}/finish`, { method: 'POST' });
    }
    // Fire-and-forget: scoring runs 60s+ server-side regardless of whether this
    // request survives; the outcome is read by polling /score.
    fetch(`/sessions/${sessionId}/score-run`, { method: 'POST' }).catch(() => {});
    const data = await pollScore();
    $('result').classList.remove('hidden');
    const sid = sessionId;
    await renderResult($('result'), data, {
      onDispute: (comment) => api(`/sessions/${sid}/dispute`, { method: 'POST', json: { comment } }),
    });
    $('after-actions').classList.remove('hidden');
    busy = false;
    $('processing').classList.add('hidden');
    $('result').scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    addBubble('system', 'Ошибка оценки: ' + err.message);
    setBusy(false);
    $('text-input').disabled = false;
  }
}

async function pollScore() {
  // The server caps a scoring run at ~270s; past this the run is lost, not slow.
  const deadline = Date.now() + 6 * 60 * 1000;
  let networkRetries = 0;
  while (true) {
    if (Date.now() > deadline) throw new Error('оценка заняла слишком много времени — нажмите «Завершить и получить оценку» ещё раз');
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
    if (data.status === 'finish_error') throw new Error(data.detail || 'оценка не удалась');
    await new Promise((r) => setTimeout(r, 3000));
  }
}

function backToCatalog() {
  sessionId = null;
  $('session-view').classList.add('hidden');
  $('catalog-view').classList.remove('hidden');
  loadHistory();
}

document.addEventListener('click', (e) => {
  const id = e.target.dataset && e.target.dataset.start;
  if (id) startSession(id);
});
$('product-filter').addEventListener('change', renderCards);
$('difficulty-filter').addEventListener('change', renderCards);
$('topic-filter').addEventListener('change', renderCards);
$('send-btn').addEventListener('click', sendTurn);
$('audio-player').addEventListener('error', () => {
  if ($('audio-player').getAttribute('src')) addBubble('system', 'Озвучка временно недоступна — прочитайте ответ клиента.');
});
$('text-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendTurn(); });
$('finish-btn').addEventListener('click', finishSession);
$('repeat-btn').addEventListener('click', () => startSession(currentScenarioId));
$('back-btn').addEventListener('click', backToCatalog);
const mic = $('mic-btn');
mic.addEventListener('mousedown', startRecording);
mic.addEventListener('mouseup', stopRecording);
mic.addEventListener('mouseleave', stopRecording);
mic.addEventListener('touchstart', (e) => { e.preventDefault(); startRecording(); });
mic.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });

function syncActiveNav() {
  setActiveNav(location.hash === '#history' ? 'history' : 'train');
}
window.addEventListener('hashchange', syncActiveNav);

(async () => {
  me = await initPage(null);
  syncActiveNav();
  if (!me.can_train) {
    location.href = me.can_dashboard ? '/dashboard' : '/admin';
    return;
  }
  scenarios = await api('/scenarios');
  const products = [...new Map(scenarios.map((s) => [s.product_id, s.product_name])).entries()];
  $('product-filter').innerHTML += products.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join('');
  const topics = [...new Map(scenarios.flatMap((s) => s.topics).map((t) => [t.id, t.name])).entries()];
  $('topic-filter').innerHTML += topics.map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join('');
  renderCards();
  loadHistory();
  const repeat = new URLSearchParams(location.search).get('repeat');
  if (repeat) startSession(repeat);
})();
