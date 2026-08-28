/*
  Dashboard en vivo: sondea /api/status y /api/counts cada 3s y
  actualiza el DOM en el lugar (sin recrear nodos) para que los
  contadores de GSAP puedan animar de un valor al siguiente como un
  velocímetro, no como un parpadeo de texto.
*/

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const POLL_MS = 3000;

// initTheme() vive en theme.js (compartido entre páginas) y ya se
// autoejecuta al cargar ese script.

// --- Contador animado ---------------------------------------------------

function animateValue(el, from, to) {
  if (REDUCED_MOTION || typeof gsap === 'undefined') {
    el.textContent = to;
    return;
  }
  const obj = { v: from };
  gsap.to(obj, {
    v: to,
    duration: 0.5,
    ease: 'power2.out',
    onUpdate: () => { el.textContent = Math.round(obj.v); }
  });
}

// --- Estado renderizado (para animar diffs, no recrear DOM) -------------

const rendered = {
  heroValues: { total: 0, in: 0, out: 0, net: 0 },
  laneCards: new Map(), // lane_id -> { el, inEl, outEl, totalEl, vtBody }
};

function renderStatus(status) {
  const bar = document.getElementById('status-bar');
  const statusClass = status.status === 'running' ? 'status-running'
    : status.status === 'error' ? 'status-error' : 'status-starting';

  bar.innerHTML = `
    <span class="pill ${statusClass}"><span class="dot"></span>${status.status}</span>
    <span class="pill">fuente <span class="value">${status.camera_source}</span></span>
    <span class="pill">resolución <span class="value">${status.frame_width}×${status.frame_height}</span></span>
    <span class="pill">fps <span class="value">${status.fps_estimate}</span></span>
    ${status.last_error ? `<span class="pill status-error">${status.last_error}</span>` : ''}
  `;
}

function renderHero(counts) {
  const totals = counts.reduce((acc, c) => {
    acc.in += c.in || 0;
    acc.out += c.out || 0;
    return acc;
  }, { in: 0, out: 0 });
  const total = totals.in + totals.out;
  const net = totals.in - totals.out;

  const targets = { total, in: totals.in, out: totals.out, net };
  for (const key of Object.keys(targets)) {
    const el = document.getElementById(`hero-${key}`);
    if (rendered.heroValues[key] !== targets[key]) {
      animateValue(el, rendered.heroValues[key], targets[key]);
      rendered.heroValues[key] = targets[key];
    }
  }
}

function vehicleTypeRows(byType) {
  const entries = Object.entries(byType);
  if (!entries.length) return '<div class="vt-row"><span class="vt-name">—</span></div>';
  const maxTotal = Math.max(...entries.map(([, v]) => (v.in || 0) + (v.out || 0)), 1);
  return entries.map(([type, v]) => {
    const vin = v.in || 0, vout = v.out || 0;
    const inPct = (vin / maxTotal) * 100;
    const outPct = (vout / maxTotal) * 100;
    return `
      <div class="vt-row">
        <span class="vt-name">${type}</span>
        <span class="vt-bar"><span class="seg-in" style="width:${inPct}%"></span><span class="seg-out" style="width:${outPct}%"></span></span>
        <span class="vt-count">${vin} / ${vout}</span>
      </div>`;
  }).join('');
}

function renderLanes(counts) {
  const grid = document.getElementById('lane-grid');
  const seenIds = new Set(counts.map(c => c.lane_id));

  // Quitar carriles que ya no existen
  for (const [laneId, entry] of rendered.laneCards) {
    if (!seenIds.has(laneId)) {
      entry.el.remove();
      rendered.laneCards.delete(laneId);
    }
  }

  if (!counts.length && rendered.laneCards.size === 0) {
    grid.innerHTML = '<div class="empty-state">Sin cruces registrados todavía — el conteo aparece aquí en cuanto un vehículo cruce una línea configurada.</div>';
    return;
  }
  const emptyState = grid.querySelector('.empty-state');
  if (emptyState) emptyState.remove();

  counts.forEach(c => {
    let entry = rendered.laneCards.get(c.lane_id);
    const isNew = !entry;

    if (isNew) {
      const card = document.createElement('div');
      card.className = 'lane-card';
      card.innerHTML = `
        <div class="lane-head">
          <span class="lane-name"></span>
          <span class="lane-total"></span>
        </div>
        <div class="lane-io">
          <div class="io-item"><div class="io-label">Entrada</div><div class="io-value" data-in>0</div></div>
          <div class="io-item"><div class="io-label">Salida</div><div class="io-value" data-out>0</div></div>
        </div>
        <div class="vt-body"></div>
      `;
      grid.appendChild(card);
      entry = {
        el: card,
        nameEl: card.querySelector('.lane-name'),
        totalEl: card.querySelector('.lane-total'),
        inEl: card.querySelector('[data-in]'),
        outEl: card.querySelector('[data-out]'),
        vtBody: card.querySelector('.vt-body'),
        values: { in: 0, out: 0, total: 0 },
      };
      rendered.laneCards.set(c.lane_id, entry);
      if (!REDUCED_MOTION && typeof gsap !== 'undefined') {
        gsap.from(card, { opacity: 0, y: 12, duration: 0.4, ease: 'power2.out' });
      }
    }

    entry.nameEl.textContent = c.lane_name;
    if (entry.values.in !== c.in) { animateValue(entry.inEl, entry.values.in, c.in || 0); entry.values.in = c.in || 0; }
    if (entry.values.out !== c.out) { animateValue(entry.outEl, entry.values.out, c.out || 0); entry.values.out = c.out || 0; }
    if (entry.values.total !== c.total) { animateValue(entry.totalEl, entry.values.total, c.total || 0); entry.values.total = c.total || 0; }
    entry.vtBody.innerHTML = vehicleTypeRows(c.by_vehicle_type || {});
  });
}

async function refresh() {
  try {
    const [statusRes, countsRes] = await Promise.all([fetch('/api/status'), fetch('/api/counts')]);
    if (!statusRes.ok || !countsRes.ok) throw new Error('respuesta no OK de la API');
    renderStatus(await statusRes.json());
    const counts = await countsRes.json();
    renderHero(counts);
    renderLanes(counts);
  } catch (e) {
    document.getElementById('status-bar').innerHTML =
      `<span class="pill status-error">No se pudo conectar con la API — reintentando…</span>`;
  }
}

function entranceAnimation() {
  // Entrada: power2.out para UI estándar (topbar), power3.out para el
  // revelado más dramático del cluster de instrumentos (el "hero" de
  // la página) — según la guía de easing de GSAP para animaciones de
  // entrada.
  if (REDUCED_MOTION || typeof gsap === 'undefined') return;
  gsap.timeline()
    .from('.topbar', { opacity: 0, y: -8, duration: 0.4, ease: 'power2.out' })
    .from('.stat-tile', { opacity: 0, y: 18, duration: 0.6, stagger: 0.07, ease: 'power3.out' }, '-=0.15');
}

entranceAnimation();
refresh();
setInterval(refresh, POLL_MS);
