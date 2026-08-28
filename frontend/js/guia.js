/*
  Guía de primeros pasos.

  No es un tour de diapositivas: cada paso se marca como completado
  leyendo el estado REAL del proyecto (¿existe?, ¿tiene videos?,
  ¿tiene carriles?, ¿ya hay conteos?). Eso la hace útil también para
  alguien que vuelve a mitad del proceso — que es el caso normal aquí,
  porque un aforo se levanta en varias sesiones.

  El "momento de valor" del producto es ver el reporte con el FHP
  calculado a partir de su propio video, así que la guía apunta ahí.

  Se puede cerrar en cualquier momento y no vuelve a aparecer.
*/

const GUIDE_DISMISSED_KEY = 'guia-dismissed';

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
    body: 'Dibuja la línea justo donde cruzan los vehículos y ponle nombre. Sin esto el conteo no arranca.',
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

async function readProgress() {
  const state = { projectCount: 0, videoCount: 0, laneCount: 0, crossingCount: 0, projectId: null };
  try {
    const res = await fetch('/api/projects');
    if (!res.ok) return state;
    const projects = await res.json();
    state.projectCount = projects.length;
    if (!projects.length) return state;

    // El proyecto de referencia es el que el usuario está viendo, o el
    // más avanzado — para no marcar el progreso contra uno vacío.
    const fromUrl = new URLSearchParams(location.search).get('project');
    const current = projects.find(p => String(p.id) === fromUrl)
      || projects.slice().sort((a, b) => b.crossing_count - a.crossing_count)[0];

    state.projectId = current.id;
    state.videoCount = current.video_count;
    state.laneCount = current.lane_count;
    state.crossingCount = current.crossing_count;
  } catch (e) { /* sin red, la guía simplemente no se muestra */ }
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

async function initGuia() {
  const host = document.getElementById('guia-host');
  if (!host) return;
  if (localStorage.getItem(GUIDE_DISMISSED_KEY) === '1') return;

  const state = await readProgress();
  const results = GUIDE_STEPS.map(s => s.done(state));

  // Si ya completó todo, la guía cumplió su función y desaparece sola.
  if (results.every(Boolean)) return;

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

  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && typeof gsap !== 'undefined') {
    gsap.from(host.querySelector('.guia'), { opacity: 0, y: -10, duration: 0.4, ease: 'power2.out' });
  }
}

initGuia();
