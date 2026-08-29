/*
  Guía de primeros pasos.

  No es un tour de diapositivas: cada paso se marca como completado
  leyendo el estado REAL del proyecto (¿existe?, ¿tiene videos?,
  ¿tiene carriles?, ¿ya hay conteos?). Eso la hace útil también para
  alguien que vuelve a mitad del proceso — que es el caso normal aquí,
  porque un aforo se levanta en varias sesiones.

  Se refresca sola: antes solo se dibujaba al cargar la página, así que
  si subías un video o creabas un carril sin recargar, la guía seguía
  mostrando el paso anterior y parecía descompuesta. Ahora vuelve a leer
  el estado periódicamente y también sigue al selector de intersección,
  para no reportar el avance de un proyecto distinto al que estás viendo.
*/

const GUIDE_DISMISSED_KEY = 'guia-dismissed';
const GUIDE_POLL_MS = 4000;

const GUIDE_STEPS = [
  {
    id: 'crear',
    title: 'Crea la intersección',
    body: 'Cada punto donde mides tránsito es un proyecto. Ahí se acumula todo su histórico.',
    action: { label: 'Ir a Proyectos', href: 'proyectos.html' },
    done: s => s.projectCount > 0,
  },
  {
    id: 'subir',
    title: 'Sube los videos',
    body: 'Uno o varios segmentos. Si son partes de la misma hora, se unen solos en el reporte.',
    action: { label: 'Subir videos', href: 'subir.html' },
    done: s => s.videoCount > 0,
  },
  {
    id: 'calibrar',
    title: 'Marca los carriles',
    body: 'Dibuja la línea cruzando el carril completo, justo donde pasan los vehículos, y presiona "Empezar conteo".',
    action: { label: 'Calibrar', href: 'calibrar.html' },
    done: s => s.laneCount > 0,
  },
  {
    id: 'contar',
    title: 'Consulta el reporte',
    body: 'Volumen por intervalo, hora de máxima demanda y factor de hora pico (FHP).',
    action: { label: 'Ver reporte', href: 'reporte.html' },
    done: s => s.crossingCount > 0,
  },
];

// Firma del último render, para no repintar (ni re-animar) cuando nada
// cambió — si no, la guía parpadearía cada 4 segundos.
let lastSignature = null;

function currentProjectId(projects) {
  // Prioridad: el selector de la página, luego la URL, y como último
  // recurso el proyecto más avanzado.
  //
  // El selector va primero porque es el control vivo que el usuario está
  // manipulando: si cambia de intersección en el desplegable, la URL sigue
  // teniendo la anterior, y hacer ganar a la URL dejaba la guía mostrando
  // el avance del proyecto equivocado.
  const select = document.getElementById('project-select');
  if (select && select.value && projects.some(p => String(p.id) === select.value)) {
    return select.value;
  }

  const fromUrl = new URLSearchParams(location.search).get('project');
  if (fromUrl && projects.some(p => String(p.id) === fromUrl)) return fromUrl;

  if (!projects.length) return null;
  return String(projects.slice().sort((a, b) => b.crossing_count - a.crossing_count)[0].id);
}

async function readProgress() {
  const state = { projectCount: 0, videoCount: 0, laneCount: 0, crossingCount: 0, projectId: null };
  try {
    const res = await fetch('/api/projects');
    if (!res.ok) return state;
    const projects = await res.json();
    state.projectCount = projects.length;
    if (!projects.length) return state;

    const id = currentProjectId(projects);
    const current = projects.find(p => String(p.id) === String(id));
    if (!current) return state;

    state.projectId = current.id;
    state.videoCount = current.video_count;
    state.laneCount = current.lane_count;
    state.crossingCount = current.crossing_count;
  } catch (e) { /* sin red, la guía simplemente no se actualiza */ }
  return state;
}

function stepIcon(done, isCurrent) {
  if (done) {
    return `<span class="gs-mark done" aria-label="Completado">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5">
        <path d="M20 6L9 17l-5-5"/></svg></span>`;
  }
  return `<span class="gs-mark${isCurrent ? ' current' : ''}" aria-hidden="true"></span>`;
}

async function refreshGuia() {
  const host = document.getElementById('guia-host');
  if (!host) return;

  if (localStorage.getItem(GUIDE_DISMISSED_KEY) === '1') {
    if (host.innerHTML) host.innerHTML = '';
    lastSignature = null;
    return;
  }

  const state = await readProgress();
  const results = GUIDE_STEPS.map(s => s.done(state));

  // Si ya completó todo, la guía cumplió su función y desaparece sola.
  if (results.every(Boolean)) {
    host.innerHTML = '';
    lastSignature = 'completa';
    return;
  }

  const signature = `${state.projectId}:${results.join(',')}`;
  if (signature === lastSignature) return;   // nada cambió, no repintar
  const isFirstRender = lastSignature === null;
  lastSignature = signature;

  const currentIndex = results.findIndex(r => !r);
  const q = state.projectId ? `?project=${state.projectId}` : '';

  const items = GUIDE_STEPS.map((step, i) => {
    const done = results[i];
    const isCurrent = i === currentIndex;
    return `
      <li class="guia-step${done ? ' done' : ''}${isCurrent ? ' current' : ''}">
        ${stepIcon(done, isCurrent)}
        <div class="gs-text">
          <div class="gs-title">${step.title}</div>
          ${isCurrent ? `<div class="gs-body">${step.body}</div>` : ''}
        </div>
        ${isCurrent ? `<a class="gs-action" href="${step.action.href}${step.action.href === 'proyectos.html' ? '' : q}">${step.action.label}</a>` : ''}
      </li>`;
  }).join('');

  host.innerHTML = `
    <section class="guia" aria-labelledby="guia-title">
      <div class="guia-head">
        <div>
          <h2 id="guia-title">Primeros pasos</h2>
          <p class="guia-sub">Paso ${currentIndex + 1} de ${GUIDE_STEPS.length} — la guía se cierra sola al terminar.</p>
        </div>
        <button type="button" class="guia-close" id="guia-close" aria-label="Cerrar guía">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </div>
      <ol class="guia-steps">${items}</ol>
    </section>`;

  document.getElementById('guia-close').addEventListener('click', () => {
    localStorage.setItem(GUIDE_DISMISSED_KEY, '1');
    const el = host.querySelector('.guia');
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && typeof gsap !== 'undefined') {
      gsap.to(el, { opacity: 0, y: -8, duration: 0.25, onComplete: () => (host.innerHTML = '') });
    } else {
      host.innerHTML = '';
    }
  });

  // Solo se anima la primera aparición; en las actualizaciones el contenido
  // cambia en el lugar, sin llamar la atención de golpe.
  if (isFirstRender && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
      && typeof gsap !== 'undefined') {
    gsap.from(host.querySelector('.guia'), { opacity: 0, y: -10, duration: 0.4, ease: 'power2.out' });
  }
}

/** Vuelve a mostrar la guía después de haberla cerrado. */
function reabrirGuia() {
  localStorage.removeItem(GUIDE_DISMISSED_KEY);
  lastSignature = null;
  refreshGuia();
}

refreshGuia();
setInterval(refreshGuia, GUIDE_POLL_MS);

// Reaccionar de inmediato al cambiar de intersección, sin esperar al sondeo.
document.addEventListener('change', e => {
  if (e.target && e.target.id === 'project-select') {
    lastSignature = null;
    refreshGuia();
  }
});
