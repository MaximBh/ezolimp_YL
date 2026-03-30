const API_URL = `http://${window.location.hostname || '127.0.0.1'}:8000`;
const loginHTML = `
<h3 class="text-2xl font-bold text-primary mb-6">Вход в систему</h3>
<form id="loginForm" class="space-y-4">
  <div>
    <label class="block text-gray-dark mb-2">Имя пользователя</label>
    <input type="text" id="loginUsername" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-accent" required>
 </div>
  <div>
    <label class="block text-gray-dark mb-2">Пароль</label>
    <input type="password" id="loginPassword" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-accent" required>
 </div>
  <button type="submit" class="w-full bg-accent text-white py-3 rounded-lg font-medium hover:bg-orange-600 transition-colors duration-200">Войти</button>
</form>
<p class="mt-4 text-center text-gray-dark">Нет аккаунта? <button id="switchToRegister" class="text-accent font-medium hover:text-orange-600">Зарегистрироваться</button></p>
`;

const registerHTML = `
<h3 class="text-2xl font-bold text-primary mb-6">Регистрация</h3>
<form id="registerForm" class="space-y-4">
  <div>
    <label class="block text-gray-dark mb-2">Имя пользователя</label>
    <input type="text" id="regUsername" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-accent" required>
 </div>
  <div>
    <label class="block text-gray-dark mb-2">Полное имя</label>
    <input type="text" id="regFullName" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-accent" required>
 </div>
  <div>
    <label class="block text-gray-dark mb-2">Email</label>
    <input type="email" id="regEmail" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-accent" required>
 </div>
  <div>
    <label class="block text-gray-dark mb-2">Школа</label>
    <input type="text" id="regSchool" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-accent" required>
 </div>
  <div>
    <label class="block text-gray-dark mb-2">Класс</label>
    <input type="number" id="regGrade" min="1" max="11" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-accent" required>
 </div>
  <div>
    <label class="block text-gray-dark mb-2">Пароль</label>
    <input type="password" id="regPassword" class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-accent" required>
 </div>
  <button type="submit" class="w-full bg-accent text-white py-3 rounded-lg font-medium hover:bg-orange-600 transition-colors duration-200">Зарегистрироваться</button>
</form>
<p class="mt-4 text-center text-gray-dark">Уже есть аккаунт? <button id="switchToLogin" class="text-accent font-medium hover:text-orange-600">Войти</button></p>
`;

function showAuthModal(mode = 'login') {
  const modal = document.createElement('div');
  modal.id = 'authModal';
  modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4';
  modal.innerHTML = `
    <div class="bg-white rounded-xl shadow-2xl max-w-md w-full overflow-hidden">
      <div class="p-6" id="authContent">${mode === 'login' ? loginHTML : registerHTML}</div>
   </div>
  `;
  document.body.appendChild(modal);
  
  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      modal.remove();
    }
  });
  
  addAuthEventListeners();
}

function addAuthEventListeners() {
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const switchToRegister = document.getElementById('switchToRegister');
  const switchToLogin = document.getElementById('switchToLogin');
  const authContent = document.getElementById('authContent');

  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const username = document.getElementById('loginUsername').value;
      const password = document.getElementById('loginPassword').value;

      try {
        const response = await fetch(`${API_URL}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });

        if (response.ok) {
          const data = await response.json();
          localStorage.setItem('token', data.token);
          localStorage.setItem('user', JSON.stringify(data.user));
          document.getElementById('authModal').remove();
          alert('Вы успешно вошли в систему!');
          location.reload();
        } else {
          const error = await response.json();
          alert(error.error || 'Ошибка входа');
        }
      } catch (error) {
        alert('Ошибка подключения к серверу');
      }
    });
  }

  if (registerForm) {
    registerForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const userData = {
        username: document.getElementById('regUsername').value,
        email: document.getElementById('regEmail').value,
        password: document.getElementById('regPassword').value,
        full_name: document.getElementById('regFullName').value,
        school: document.getElementById('regSchool').value,
        grade: parseInt(document.getElementById('regGrade').value)
      };

      try {
        const response = await fetch(`${API_URL}/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(userData)
        });

        if (response.ok) {
          alert('Регистрация прошла успешно! Теперь войдите в систему.');
          authContent.innerHTML = loginHTML;
          addAuthEventListeners();
        } else {
          const error = await response.json();
          alert(error.error || 'Ошибка регистрации');
        }
      } catch (error) {
        alert('Ошибка подключения к серверу');
      }
    });
  }

  if (switchToRegister) {
    switchToRegister.addEventListener('click', () => {
      authContent.innerHTML = registerHTML;
      addAuthEventListeners();
    });
  }

  if (switchToLogin) {
    switchToLogin.addEventListener('click', () => {
      authContent.innerHTML = loginHTML;
      addAuthEventListeners();
    });
  }
}

window.showAuthModal = showAuthModal;
