// My progress: the user's own analytics exactly as /me/progress returns them.
// The backend owns every number; rendering lives in progress-view.js.

const $ = (id) => document.getElementById(id);

(async () => {
  try {
    await initPage('progress');
  } catch { return; }
  const content = $('content');
  try {
    const p = await api('/me/progress');
    if (!p.sessions.scored) {
      content.innerHTML = `<div class="panel">${stateHtml('empty', 'Пока нет оценённых тренировок', 'Прогресс появится после первой тренировки, получившей оценку.')}
        ${scopeNote(p.sessions)}<div class="row justify-center"><a class="btn" href="/">Начать тренировку</a></div></div>`;
      return;
    }
    renderProgress(content, p);
  } catch (err) {
    content.innerHTML = `<div class="panel">${stateHtml('error', 'Не удалось загрузить прогресс', err.message)}</div>`;
  }
})();
