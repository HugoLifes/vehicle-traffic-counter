/*
  Navegación compartida por todas las páginas.

  Está en dos niveles a propósito, porque la app tiene dos modos que no
  son del mismo nivel jerárquico:

    Global   →  Proyectos  |  Cámara en vivo
    Local    →  (dentro de un proyecto)  Subir · Calibrar · Reporte

  Antes eran 5 enlaces planos, lo que mezclaba el flujo de trabajo de un
  proyecto (subir → calibrar → reporte) con un modo completamente
  distinto (la cámara en vivo). También faltaba orientación: estando en
  "Calibrar" no había forma de saber qué intersección estabas calibrando.
  Ahora el nombre del proyecto viaja en la barra local.

  El estado activo se marca con color + peso + barra indicadora, nunca
  solo con color.
*/

const NAV_GLOBAL = [
  { id: 'proyectos', href: 'proyectos.html', label: 'Proyectos' },
  { id: 'dashboard', href: 'dashboard.html', label: 'Cámara en vivo' },
];

// Pasos del flujo dentro de un proyecto, en el orden en que se recorren.
const NAV_PROJECT = [
  { id: 'subir', href: 'subir.html', label: 'Subir videos' },
  { id: 'calibrar', href: 'calibrar.html', label: 'Calibrar' },
  { id: 'reporte', href: 'reporte.html', label: 'Reporte' },
];

const BRAND_SVG = `
  <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
    <rect x="2" y="2" width="20" height="20" rx="5" stroke-opacity="0.35"/>
    <path d="M7 16 L7 8 L11 8" /><path d="M9.5 5.5 L7 8 L9.5 10.5" />
    <path d="M17 8 L17 16 L13 16" /><path d="M14.5 18.5 L17 16 L14.5 13.5" />
  </svg>`;

/**
 * @param {object} opts
 *   current   — id de la página actual
 *   title     — título de la página
 *   subtitle  — bajada descriptiva
 *   projectScoped — si true, muestra la barra local del proyecto
 */
function renderNav({ current, title, subtitle, projectScoped = false }) {
  const host = document.getElementById('nav-host');
  if (!host) return;

  const projectId = new URLSearchParams(location.search).get('project');
  const q = projectId ? `?project=${projectId}` : '';

  const globalLinks = NAV_GLOBAL.map(item => {
    const active = item.id === current || (projectScoped && item.id === 'proyectos');
    return `<a href="${item.href}" class="nav-link${active ? ' active' : ''}"
               ${active ? 'aria-current="page"' : ''}>${item.label}</a>`;
  }).join('');

  const localBar = projectScoped ? `
    <div class="nav-local">
      <div class="nav-project" id="nav-project-name">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M12 21s-7-6-7-11a7 7 0 1114 0c0 5-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>
        </svg>
        <span class="np-name">—</span>
      </div>
      <nav class="nav-steps" aria-label="Pasos del proyecto">
        ${NAV_PROJECT.map((item, i) => {
          const active = item.id === current;
          return `<a href="${item.href}${q}" class="nav-step${active ? ' active' : ''}"
                     ${active ? 'aria-current="page"' : ''}>
                    <span class="step-num">${i + 1}</span>${item.label}
                  </a>`;
        }).join('')}
      </nav>
    </div>` : '';

  host.innerHTML = `
    <div class="topbar">
      <a class="brand" href="proyectos.html">
        ${BRAND_SVG}
        <div>
          <h1>${title}</h1>
          <div class="tagline">${subtitle}</div>
        </div>
      </a>
      <div class="topbar-right">
        <nav class="nav-links" aria-label="Navegación principal">${globalLinks}</nav>
        <button class="theme-toggle" id="theme-toggle" aria-label="Cambiar tema"></button>
      </div>
    </div>
    ${localBar}
  `;

  if (projectScoped && projectId) fillProjectName(projectId);
}

async function fillProjectName(projectId) {
  try {
    const res = await fetch(`/api/projects/${projectId}`);
    if (!res.ok) return;
    const p = await res.json();
    const el = document.querySelector('#nav-project-name .np-name');
    if (el) el.textContent = p.name;
  } catch (e) { /* sin nombre, la página sigue siendo usable */ }
}

/** Mantiene ?project= en la barra local cuando cambia el selector. */
function syncNavProject(projectId, projectName) {
  document.querySelectorAll('.nav-step').forEach(a => {
    const base = a.getAttribute('href').split('?')[0];
    a.setAttribute('href', projectId ? `${base}?project=${projectId}` : base);
  });
  const el = document.querySelector('#nav-project-name .np-name');
  if (el) el.textContent = projectName || '—';
}
