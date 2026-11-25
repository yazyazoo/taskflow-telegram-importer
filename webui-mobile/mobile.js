(() => {
  'use strict';

  const TOKEN_KEY = 'taskflow.telegram.access-token';
  const login = document.querySelector('#mobile-login');
  const form = document.querySelector('#token-form');
  const logout = document.querySelector('#logout');
  const taskflow = document.querySelector('#taskflow-mobile');

  function decorateTables(root) {
    for (const table of root.querySelectorAll('table')) {
      const labels = [...table.querySelectorAll('thead th')]
        .map((cell) => cell.textContent?.trim() || '');
      for (const row of table.querySelectorAll('tbody tr')) {
        [...row.querySelectorAll('td')].forEach((cell, index) => {
          const label = labels[index] || '';
          if (cell.dataset.mobileLabel !== label) cell.dataset.mobileLabel = label;
        });
      }
    }
  }

  function installMobileLayout() {
    const root = taskflow.shadowRoot;
    if (!root || root.querySelector('link[data-taskflow-mobile]')) return;
    const stylesheet = document.createElement('link');
    stylesheet.rel = 'stylesheet';
    stylesheet.href = new URL('./mobile.css', window.location.href).href;
    stylesheet.dataset.taskflowMobile = 'true';
    root.append(stylesheet);
    decorateTables(root);
    new MutationObserver(() => decorateTables(root)).observe(root, {
      childList: true,
      subtree: true,
    });
  }

  function connect(token) {
    localStorage.setItem(TOKEN_KEY, token);
    login.hidden = true;
    logout.hidden = false;
    taskflow.hidden = false;
    taskflow.configure({
      apiUrl: window.location.origin,
      accessToken: token,
    });
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const token = new FormData(form).get('access-token')?.toString().trim();
    if (token) connect(token);
  });

  logout.addEventListener('click', () => {
    localStorage.removeItem(TOKEN_KEY);
    window.location.reload();
  });

  customElements.whenDefined('taskflow-ui').then(() => {
    installMobileLayout();
    const token = localStorage.getItem(TOKEN_KEY)?.trim();
    if (token) connect(token);
    else login.hidden = false;
  });
})();
