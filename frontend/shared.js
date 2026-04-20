/* shared.js — подключается на всех страницах */

const API_URL = `http://${window.location.hostname || '127.0.0.1'}:8001`;
const html = document.documentElement;

/* ── ТЕМА ── */
(function() {
  const saved = localStorage.getItem('ez-theme') || 'light';
  html.setAttribute('data-theme', saved);
})();

document.addEventListener('DOMContentLoaded', () => {

  /* тема */
  const themeBtn = document.getElementById('themeBtn');

  function applyTheme(theme) {
    html.setAttribute('data-theme', theme);
    if (themeBtn) {
      const dark = theme === 'dark';
      themeBtn.innerHTML = dark
        ? `<svg viewBox="0 0 24 24" style="width:15px;height:15px;stroke:var(--text2);fill:none;stroke-width:2;stroke-linecap:round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`
        : `<svg viewBox="0 0 24 24" style="width:15px;height:15px;stroke:var(--text2);fill:none;stroke-width:2;stroke-linecap:round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
    }
  }

  applyTheme(localStorage.getItem('ez-theme') || 'light');

  // синхронизация темы между вкладками
  const themeChannel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('ez-theme') : null;
  if (themeChannel) {
    themeChannel.onmessage = e => applyTheme(e.data);
  } else {
    // fallback для браузеров без BroadcastChannel
    window.addEventListener('storage', e => {
      if (e.key === 'ez-theme' && e.newValue) applyTheme(e.newValue);
    });
  }

  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      localStorage.setItem('ez-theme', next);
      applyTheme(next);
      if (themeChannel) themeChannel.postMessage(next);
    });
  }

  /* бургер */
  const burgerBtn = document.getElementById('burgerBtn');
  const mobileMenu = document.getElementById('mobileMenu');
  if (burgerBtn && mobileMenu) {
    burgerBtn.addEventListener('click', () => mobileMenu.classList.toggle('open'));
    document.addEventListener('click', e => {
      if (!burgerBtn.contains(e.target) && !mobileMenu.contains(e.target))
        mobileMenu.classList.remove('open');
    });
  }

  /* аватар дропдаун */
  const avatarBtn = document.getElementById('navAvatarBtn');
  const avatarDrop = document.getElementById('navAvatarDrop');
  if (avatarBtn && avatarDrop) {
    avatarBtn.addEventListener('click', e => {
      e.stopPropagation();
      avatarDrop.classList.toggle('open');
    });
    document.addEventListener('click', () => avatarDrop.classList.remove('open'));
  }

  /* выход */
  const logoutBtn = document.getElementById('logoutBtn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = 'main.html';
    });
  }

  /* auth состояние */
  const token = localStorage.getItem('token');
  const loginBtn = document.getElementById('loginBtn');
  const avatarWrap = document.getElementById('navAvatarWrap');

  if (token) {
    if (loginBtn) loginBtn.style.display = 'none';
    if (avatarWrap) avatarWrap.classList.add('visible');
    loadNavAvatar(token);
  } else {
    if (avatarWrap) avatarWrap.style.display = 'none';
  }

  async function loadNavAvatar(tkn) {
    try {
      const r = await fetch(`${API_URL}/auth/me`, { headers: { Authorization: tkn } });
      if (!r.ok) { clearAuth(); return; }
      const u = await r.json();
      const img = document.getElementById('navAvatarImg');
      if (img) img.src = u.avatar_url || `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(u.username)}&backgroundColor=7048b8&textColor=ffffff`;
    } catch {
      const img = document.getElementById('navAvatarImg');
      if (img) img.src = `https://api.dicebear.com/7.x/initials/svg?seed=u&backgroundColor=7048b8&textColor=ffffff`;
    }
  }

  function clearAuth() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    if (loginBtn) loginBtn.style.display = '';
    if (avatarWrap) { avatarWrap.classList.remove('visible'); avatarWrap.style.display = 'none'; }
  }

  /* ── МОДАЛЬНОЕ ОКНО АВТОРИЗАЦИИ ── */
  function openAuthModal(mode = 'login') {
    if (document.getElementById('_authModal')) return;
    const overlay = document.createElement('div');
    overlay.id = '_authModal';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(4px)';

    const box = document.createElement('div');
    box.style.cssText = 'background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:36px;max-width:420px;width:100%;max-height:90vh;overflow-y:auto;position:relative';

    function renderLogin() {
      box.innerHTML = `
        <button id="_authClose" style="position:absolute;top:16px;right:18px;background:none;border:none;font-size:22px;cursor:pointer;color:var(--text3);line-height:1">×</button>
        <div style="font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--accent);margin-bottom:14px">Вход</div>
        <h2 style="font-size:24px;font-weight:700;margin-bottom:24px">Войти в EzOlimp</h2>
        <div style="margin-bottom:14px"><label style="display:block;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Имя пользователя</label><input class="input" id="_loginUser" type="text" placeholder="username" autocomplete="username"></div>
        <div style="margin-bottom:20px"><label style="display:block;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Пароль</label><input class="input" id="_loginPass" type="password" placeholder="••••••••" autocomplete="current-password"></div>
        <div id="_authErr" style="color:#dc2626;font-size:13px;margin-bottom:12px;display:none"></div>
        <button class="btn btn-accent" id="_loginSubmit" style="width:100%">Войти</button>
        <p style="text-align:center;font-size:14px;color:var(--text2);margin-top:16px">Нет аккаунта? <button id="_toReg" style="background:none;border:none;color:var(--accent);font-weight:600;cursor:pointer;font-size:14px">Зарегистрироваться</button></p>`;
      bindLogin();
    }

    function renderRegister() {
      box.innerHTML = `
        <button id="_authClose" style="position:absolute;top:16px;right:18px;background:none;border:none;font-size:22px;cursor:pointer;color:var(--text3);line-height:1">×</button>
        <div style="font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--accent);margin-bottom:14px">Регистрация</div>
        <h2 style="font-size:24px;font-weight:700;margin-bottom:24px">Создать аккаунт</h2>
        <div style="margin-bottom:12px"><label style="display:block;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Имя пользователя</label><input class="input" id="_regUser" type="text" placeholder="username"></div>
        <div style="margin-bottom:12px"><label style="display:block;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Полное имя</label><input class="input" id="_regName" type="text" placeholder="Иван Иванов"></div>
        <div style="margin-bottom:12px"><label style="display:block;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Email</label><input class="input" id="_regEmail" type="email" placeholder="email@example.com"></div>
        <div style="margin-bottom:12px"><label style="display:block;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Школа</label><input class="input" id="_regSchool" type="text" placeholder="Школа №1"></div>
        <div style="margin-bottom:12px"><label style="display:block;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Класс</label><input class="input" id="_regGrade" type="number" min="1" max="11" placeholder="10"></div>
        <div style="margin-bottom:20px"><label style="display:block;font-size:12px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px">Пароль</label><input class="input" id="_regPass" type="password" placeholder="••••••••"></div>
        <div id="_authErr" style="color:#dc2626;font-size:13px;margin-bottom:12px;display:none"></div>
        <button class="btn btn-accent" id="_regSubmit" style="width:100%">Зарегистрироваться</button>
        <p style="text-align:center;font-size:14px;color:var(--text2);margin-top:16px">Уже есть аккаунт? <button id="_toLogin" style="background:none;border:none;color:var(--accent);font-weight:600;cursor:pointer;font-size:14px">Войти</button></p>`;
      bindRegister();
    }

    function showErr(msg) {
      const el = document.getElementById('_authErr');
      if (el) { el.textContent = msg; el.style.display = 'block'; }
    }

    function bindLogin() {
      document.getElementById('_authClose').onclick = () => overlay.remove();
      document.getElementById('_toReg').onclick = renderRegister;
      document.getElementById('_loginSubmit').onclick = async () => {
        const btn = document.getElementById('_loginSubmit');
        btn.disabled = true; btn.textContent = 'Вход...';
        try {
          const r = await fetch(`${API_URL}/auth/login`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: document.getElementById('_loginUser').value, password: document.getElementById('_loginPass').value })
          });
          const d = await r.json();
          if (!r.ok) { showErr(d.error || 'Ошибка входа'); btn.disabled = false; btn.textContent = 'Войти'; return; }
          localStorage.setItem('token', d.token);
          localStorage.setItem('user', JSON.stringify(d.user));
          overlay.remove();
          location.reload();
        } catch { showErr('Сервер недоступен'); btn.disabled = false; btn.textContent = 'Войти'; }
      };
      document.getElementById('_loginPass').addEventListener('keypress', e => { if (e.key === 'Enter') document.getElementById('_loginSubmit').click(); });
    }

    function bindRegister() {
      document.getElementById('_authClose').onclick = () => overlay.remove();
      document.getElementById('_toLogin').onclick = renderLogin;
      document.getElementById('_regSubmit').onclick = async () => {
        const btn = document.getElementById('_regSubmit');
        btn.disabled = true; btn.textContent = 'Регистрация...';
        try {
          const r = await fetch(`${API_URL}/auth/register`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              username: document.getElementById('_regUser').value,
              full_name: document.getElementById('_regName').value,
              email: document.getElementById('_regEmail').value,
              school: document.getElementById('_regSchool').value,
              grade: parseInt(document.getElementById('_regGrade').value) || null,
              password: document.getElementById('_regPass').value
            })
          });
          const d = await r.json();
          if (!r.ok) { showErr(d.error || 'Ошибка регистрации'); btn.disabled = false; btn.textContent = 'Зарегистрироваться'; return; }
          renderLogin();
          const el = document.getElementById('_authErr');
          if (el) { el.textContent = 'Регистрация успешна! Войдите.'; el.style.color = '#16a34a'; el.style.display = 'block'; }
        } catch { showErr('Сервер недоступен'); btn.disabled = false; btn.textContent = 'Зарегистрироваться'; }
      };
    }

    overlay.appendChild(box);
    document.body.appendChild(overlay);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    if (mode === 'register') renderRegister(); else renderLogin();
  }

  if (loginBtn) loginBtn.addEventListener('click', () => openAuthModal('login'));
  window.openAuthModal = openAuthModal;

  /* scroll-анимации */
  const io = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const el = entry.target;
      setTimeout(() => el.classList.add('visible'), +el.dataset.delay || 0);
      io.unobserve(el);
    });
  }, { threshold: 0.08 });

  document.querySelectorAll('.fade-up').forEach((el, i) => {
    if (!el.dataset.delay) el.dataset.delay = i * 50;
    io.observe(el);
  });

  /* ── CANVAS ── */
  const canvas = document.getElementById('neural-bg');
  if (!canvas) return;
  const ctx = canvas.getContext('2d', { alpha: true });
  const N = 80, MAX_D = 200, MOUSE_D = 220;
  let W, H, nodes, mouseX = -9999, mouseY = -9999, paused = false;

  // canvas fixed — координаты просто clientX/clientY, без любых offset
  window.addEventListener('mousemove', e => {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });
  window.addEventListener('mouseleave', () => { mouseX = -9999; mouseY = -9999; });
  document.addEventListener('visibilitychange', () => {
    paused = document.hidden;
    if (!paused) requestAnimationFrame(loop);
  });

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }
  function init() {
    nodes = Array.from({ length: N }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - .5) * .4, vy: (Math.random() - .5) * .4,
      r: Math.random() * 2.2 + 1.2,
    }));
  }
  function loop() {
    if (paused) return;
    requestAnimationFrame(loop);
    ctx.clearRect(0, 0, W, H);
    const dark = html.getAttribute('data-theme') === 'dark';
    // светлая: тёмный синий на бежевом — хорошо видно
    // тёмная: яркий голубой на тёмном — светится
    const rgb   = dark ? '100,180,255' : '20,60,160';
    const lineA = dark ? 0.55 : 0.50;
    const nodeA = dark ? 0.80 : 0.75;
    const mLA   = dark ? 0.85 : 0.80;
    const mNA   = dark ? 1.00 : 1.00;
    const lineW = dark ? 1.2 : 1.1;
    const MD2 = MAX_D * MAX_D, MSD2 = MOUSE_D * MOUSE_D;

    for (let i = 0; i < N; i++) {
      const n = nodes[i];
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0 || n.x > W) n.vx *= -1;
      if (n.y < 0 || n.y > H) n.vy *= -1;
    }
    for (let i = 0; i < N; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < N; j++) {
        const b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y, d2 = dx*dx + dy*dy;
        if (d2 < MD2) {
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
          ctx.strokeStyle = `rgba(${rgb},${(1 - Math.sqrt(d2) / MAX_D) * lineA})`;
          ctx.lineWidth = lineW; ctx.stroke();
        }
      }
    }
    if (mouseX > -999) {
      for (let i = 0; i < N; i++) {
        const n = nodes[i];
        const dx = n.x - mouseX, dy = n.y - mouseY, d2 = dx*dx + dy*dy;
        if (d2 < MSD2) {
          ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.lineTo(mouseX, mouseY);
          ctx.strokeStyle = `rgba(${rgb},${(1 - Math.sqrt(d2) / MOUSE_D) * mLA})`;
          ctx.lineWidth = 1.3; ctx.stroke();
        }
      }
    }
    for (let i = 0; i < N; i++) {
      const n = nodes[i];
      const dx = n.x - mouseX, dy = n.y - mouseY;
      const near = mouseX > -999 && dx*dx + dy*dy < MSD2;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.2832);
      ctx.fillStyle = `rgba(${rgb},${near ? mNA : nodeA})`; ctx.fill();
    }
  }
  window.addEventListener('resize', () => { resize(); init(); });
  resize(); init(); requestAnimationFrame(loop);
});
