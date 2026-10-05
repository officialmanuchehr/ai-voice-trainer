// Login page. Authentication, throttling and cookies are entirely server-side;
// this only submits the form and shows the server's (safe) message.

document.getElementById('theme-row').append(themeSelect());
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('error');
  const button = document.getElementById('login-btn');
  errorEl.textContent = '';
  errorEl.classList.add('hidden');
  setLoading(button, true);
  try {
    await api('/auth/login', {
      method: 'POST',
      json: { username: document.getElementById('username').value, password: document.getElementById('password').value },
    });
    const next = new URLSearchParams(location.search).get('next');
    location.href = next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    setLoading(button, false);
  }
});
