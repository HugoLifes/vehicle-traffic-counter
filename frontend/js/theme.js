/*
  Tema claro/oscuro compartido entre todas las páginas. Sigue la
  preferencia del sistema por defecto; el botón permite forzar una
  elección que se recuerda en localStorage.
*/

const SUN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/></svg>';

function initTheme() {
  const stored = localStorage.getItem('theme');
  if (stored) document.documentElement.setAttribute('data-theme', stored);

  const btn = document.getElementById('theme-toggle');
  if (!btn) return;

  const icon = () => {
    const isDark = getComputedStyle(document.documentElement)
      .getPropertyValue('--surface-0').trim().startsWith('#0a');
    btn.innerHTML = isDark ? SUN_ICON : MOON_ICON;
  };
  icon();

  btn.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme')
      || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    icon();
  });
}

initTheme();
