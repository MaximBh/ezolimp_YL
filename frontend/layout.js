/* layout.js — вставляет nav и footer на страницу */

function renderNav(activePage) {
  const links = [
    ['main.html',       'Главная'],
    ['catalog.html',    'Каталог задач'],
    ['training.html',   'Тренировка'],
    ['pvp.html',        'PvP'],
    ['leaderboard.html','Рейтинг'],
    ['analytics.html',  'Аналитика'],
  ];

  const user = JSON.parse(localStorage.getItem('user') || '{}');
  if (user.is_admin) links.push(['admin.html', 'Админ']);
  const linksHtml = links.map(([href, label]) =>
    `<a href="${href}" class="${activePage === href ? 'active' : ''}">${label}</a>`
  ).join('');

  const logoSvg = `<svg class="logo-svg" viewBox="0 0 28 28" fill="none">
    <polygon points="14,1.5 24.5,7.5 24.5,20.5 14,26.5 3.5,20.5 3.5,7.5" stroke="var(--accent)" stroke-width="1.4" fill="none"/>
    <polygon points="14,6.5 20,10 20,18 14,21.5 8,18 8,10" stroke="var(--accent)" stroke-width=".8" fill="none" opacity=".4"/>
    <circle cx="14" cy="14" r="2" fill="var(--accent)"/>
    <line x1="14" y1="1.5" x2="14" y2="6.5" stroke="var(--accent)" stroke-width=".8" opacity=".5"/>
    <line x1="24.5" y1="7.5" x2="20" y2="10" stroke="var(--accent)" stroke-width=".8" opacity=".5"/>
    <line x1="24.5" y1="20.5" x2="20" y2="18" stroke="var(--accent)" stroke-width=".8" opacity=".5"/>
    <line x1="14" y1="26.5" x2="14" y2="21.5" stroke="var(--accent)" stroke-width=".8" opacity=".5"/>
    <line x1="3.5" y1="20.5" x2="8" y2="18" stroke="var(--accent)" stroke-width=".8" opacity=".5"/>
    <line x1="3.5" y1="7.5" x2="8" y2="10" stroke="var(--accent)" stroke-width=".8" opacity=".5"/>
  </svg>`;

  const sunIcon = `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;

  // вставляем NAV и mobile-menu ПЕРЕД page-wrap, а не внутрь него
  const pageWrap = document.querySelector('.page-wrap');
  const navHtml = `
    <nav>
      <a href="main.html" class="nav-logo">${logoSvg}<span class="nav-logo-text">Ez<em>Olimp</em></span></a>
      <div class="nav-links">${linksHtml}</div>
      <div class="nav-right">
        <button class="theme-btn" id="themeBtn" title="Сменить тему">${sunIcon}</button>
        <div class="nav-avatar-wrap" id="navAvatarWrap">
          <button class="nav-avatar-btn" id="navAvatarBtn">
            <img id="navAvatarImg" src="https://api.dicebear.com/7.x/initials/svg?seed=demo&backgroundColor=7048b8&textColor=ffffff" alt="avatar">
          </button>
          <div class="nav-avatar-drop" id="navAvatarDrop">
            <a href="profile.html">Профиль</a>
            <button id="logoutBtn">Выйти</button>
          </div>
        </div>
        <button class="btn-login" id="loginBtn" title="Войти">Войти</button>
        <button class="nav-burger" id="burgerBtn">
          <svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
        </button>
      </div>
    </nav>
    <div class="mobile-menu" id="mobileMenu">${
      links.map(([href, label]) =>
        `<a href="${href}" class="${activePage === href ? 'active' : ''}">${label}</a>`
      ).join('')
    }</div>`;

  if (pageWrap) {
    pageWrap.insertAdjacentHTML('beforebegin', navHtml);
  } else {
    document.body.insertAdjacentHTML('afterbegin', navHtml);
  }
}

function renderFooter() {
  const logoSvg = `<svg class="logo-svg" viewBox="0 0 28 28" fill="none">
    <polygon points="14,1.5 24.5,7.5 24.5,20.5 14,26.5 3.5,20.5 3.5,7.5" stroke="var(--accent)" stroke-width="1.4" fill="none"/>
    <circle cx="14" cy="14" r="2" fill="var(--accent)"/>
  </svg>`;

  const footerHtml = `
    <footer>
      <div class="footer-inner">
        <div class="footer-brand">
          <a href="main.html" class="nav-logo" style="display:inline-flex;">
            ${logoSvg}<span class="nav-logo-text">Ez<em>Olimp</em></span>
          </a>
          <p>Платформа для подготовки к олимпиадам с PvP-режимом и автоматической проверкой решений.</p>
        </div>
        <div>
          <h5>Разделы</h5>
          <ul>
            <li><a href="catalog.html">Каталог задач</a></li>
            <li><a href="training.html">Тренировка</a></li>
            <li><a href="pvp.html">PvP матчи</a></li>
            <li><a href="leaderboard.html">Рейтинг</a></li>
            <li><a href="analytics.html">Аналитика</a></li>
          </ul>
        </div>
        <div>
          <h5>Контакты</h5>
          <ul class="footer-contact-list">
            <li>
              <span class="footer-contact-label">Telegram</span>
              <a class="footer-contact-action" href="https://t.me/ezolimp?direct" target="_blank" rel="noopener noreferrer">Написать</a>
            </li>
            <li>
              <span class="footer-contact-label">Mail</span>
              <span class="footer-contact-email">ezzolimp@gmail.com</span>
              <a class="footer-contact-action" href="https://mail.google.com/mail/u/4/#inbox?compose=VpCqJQvtZJlhFFdflqJsCHWfqqKlwMNXfvWHlRGbpLZhsMzXhrlJlvHQmgbKVhqDbWZlrVL" target="_blank" rel="noopener noreferrer">Написать</a>
            </li>
          </ul>
        </div>
      </div>
      <div class="footer-bottom">
        <span>© 2026 EzOlimp</span>
        <span>Все права защищены</span>
      </div>
    </footer>`;

  const pageWrap = document.querySelector('.page-wrap');
  if (pageWrap) {
    pageWrap.insertAdjacentHTML('afterend', footerHtml);
  } else {
    document.body.insertAdjacentHTML('beforeend', footerHtml);
  }
}
