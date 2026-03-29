const API_URL = 'http://127.0.0.1:8000';

function initNavigation(currentPage = '') {
  const navHTML = `
    <div class="hidden md:flex items-center space-x-6">
      <a href="main.html" class="${currentPage === 'main' ? 'text-accent font-medium' : 'text-gray-dark hover:text-accent transition-colors duration-200'}">Главная</a>
      <a href="catalog.html" class="${currentPage === 'catalog' ? 'text-accent font-medium' : 'text-gray-dark hover:text-accent transition-colors duration-200'}">Каталог задач</a>
      <a href="training.html" class="${currentPage === 'training' ? 'text-accent font-medium' : 'text-gray-dark hover:text-accent transition-colors duration-200'}">Тренировка</a>
      <a href="pvp.html" class="${currentPage === 'pvp' ? 'text-accent font-medium' : 'text-gray-dark hover:text-accent transition-colors duration-200'}">PvP</a>
      <a href="analytics.html" class="${currentPage === 'analytics' ? 'text-accent font-medium' : 'text-gray-dark hover:text-accent transition-colors duration-200'}">Аналитика</a>
      <a href="admin.html" id="adminLink" class="hidden text-gray-dark hover:text-accent transition-colors duration-200">Админ</a>
    </div>
    <div class="flex items-center space-x-4">
      <div id="userAvatarMenu" class="hidden relative">
        <button id="avatarBtn" class="w-10 h-10 rounded-full overflow-hidden border-2 border-accent hover:border-orange-600 transition-colors">
          <img id="navAvatar" src="https://via.placeholder.com/40" alt="Avatar" class="w-full h-full object-cover">
        </button>
        <div id="avatarDropdown" class="hidden absolute right-0 mt-2 w-48 bg-white rounded-lg shadow-lg py-2 z-50">
          <a href="profile.html" class="block px-4 py-2 text-gray-dark hover:bg-gray-50 transition-colors">
            <i class="fas fa-user mr-2"></i>Профиль
          </a>
          <button id="logoutBtnDropdown" class="w-full text-left px-4 py-2 text-gray-dark hover:bg-gray-50 transition-colors">
            <i class="fas fa-sign-out-alt mr-2"></i>Выйти
          </button>
        </div>
      </div>
      <button id="loginBtn" class="bg-accent text-white px-6 py-2 rounded-lg font-medium hover:bg-orange-600 transition-colors duration-200">Войти</button>
      <button id="mobileMenuBtn" class="md:hidden text-primary text-2xl"><i class="fas fa-bars"></i></button>
    </div>
  `;

  const navContainer = document.querySelector('nav .container');
  if (navContainer) {
    const navLinks = navContainer.querySelector('.hidden.md\\:flex');
    const navButtons = navContainer.querySelector('.flex.items-center.space-x-4');
    
    if (navLinks) navLinks.outerHTML = navHTML.split('<div class="flex items-center space-x-4">')[0];
    if (navButtons) navButtons.outerHTML = '<div class="flex items-center space-x-4">' + navHTML.split('<div class="flex items-center space-x-4">')[1];
  }

  const token = localStorage.getItem('token');
  const user = JSON.parse(localStorage.getItem('user') || '{}');
  
  const loginBtn = document.getElementById('loginBtn');
  const userAvatarMenu = document.getElementById('userAvatarMenu');
  const avatarBtn = document.getElementById('avatarBtn');
  const avatarDropdown = document.getElementById('avatarDropdown');
  const navAvatar = document.getElementById('navAvatar');
  const logoutBtnDropdown = document.getElementById('logoutBtnDropdown');
  const adminLink = document.getElementById('adminLink');

  if (token) {
    loginBtn.classList.add('hidden');
    userAvatarMenu.classList.remove('hidden');
    
    loadUserAvatar(token);
    
    if (user.is_admin) {
      adminLink.classList.remove('hidden');
    }
  }

  avatarBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    avatarDropdown.classList.toggle('hidden');
  });

  document.addEventListener('click', () => {
    avatarDropdown?.classList.add('hidden');
  });

  logoutBtnDropdown?.addEventListener('click', () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = 'main.html';
  });

  loginBtn?.addEventListener('click', () => {
    window.location.href = 'main.html';
  });
}

async function loadUserAvatar(token) {
  try {
    const response = await fetch(`${API_URL}/auth/me`, {
      headers: { 'Authorization': token }
    });
    if (response.ok) {
      const userData = await response.json();
      const navAvatar = document.getElementById('navAvatar');
      if (userData.avatar_url && navAvatar) {
        navAvatar.src = userData.avatar_url;
      }
    }
  } catch (error) {}
}
