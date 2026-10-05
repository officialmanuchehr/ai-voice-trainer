// Session review page: stored result and transcript (read-only for leads/admins).

document.getElementById('back-btn').addEventListener('click', () => {
  if (history.length > 1) history.back();
  else location.href = '/';
});

(async () => {
  await initPage(null);
  const id = new URLSearchParams(location.search).get('id');
  const resultEl = document.getElementById('result');
  try {
    const [score, transcript] = await Promise.all([api(`/sessions/${encodeURIComponent(id)}/score`), api(`/sessions/${encodeURIComponent(id)}/transcript`)]);
    renderTranscript(document.getElementById('chat'), transcript.turns);
    if (score.status !== 'finished') {
      resultEl.innerHTML = stateHtml('empty', 'Сессия ещё не оценена', `Статус: ${SESSION_STATUS[score.status] || score.status}.`);
      return;
    }
    await renderResult(resultEl, score, {
      onDispute: score.own ? (comment) => api(`/sessions/${encodeURIComponent(id)}/dispute`, { method: 'POST', json: { comment } }) : null,
    });
  } catch (err) {
    resultEl.innerHTML = stateHtml('error', 'Не удалось загрузить разбор', err.message);
  }
})();
