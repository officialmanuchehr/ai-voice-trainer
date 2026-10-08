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
    const user = await api('/auth/login', {
      method: 'POST',
      json: { username: document.getElementById('username').value, password: document.getElementById('password').value },
    });
    const next = new URLSearchParams(location.search).get('next');
    // Managers land on their overview, sales leads on the team overview,
    // product and compliance (who cannot train) on their work queue; other
    // roles keep the existing default.
    const home = { manager: '/overview', sales_lead: '/dashboard', product: '/queue', compliance: '/queue' }[user.role] || '/';
    let destination = home;
    if (next) {
      try {
        const target = new URL(next, location.origin);
        if (target.origin === location.origin) destination = target.href;
      } catch (_) { /* Invalid return addresses use the role's home page. */ }
    }
    location.href = destination;
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
    setLoading(button, false);
  }
});
