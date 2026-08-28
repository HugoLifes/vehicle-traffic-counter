/*
  Reporte de aforo: métricas de ingeniería de tránsito, gráficas por
  intervalo y la tabla detallada.

  El orden no es casual — va de lo más resumido a lo más detallado:
  1. Métricas del estudio (¿cuál es la conclusión?)
  2. Gráfica por intervalo (¿cómo se distribuyó el tránsito?)
  3. Tabla exacta, plegada (¿cuáles son las cifras para el informe?)
*/

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const projectSelect = document.getElementById('project-select');
const intervalSelect = document.getElementById('report-interval');
const reportBody = document.getElementById('report-body');

function hhmm(iso) { return iso.slice(11, 16); }
function formatIntervalLabel(startIso, endIso) {
  return `${hhmm(startIso)} – ${hhmm(endIso)}`;
}

// --- Métricas del estudio ---------------------------------------------

function renderMetrics(m) {
  const peak = m.peak_hour;
  const cards = [];

  cards.push(`
    <div class="metric-card accent">
      <div class="m-label">Volumen total</div>
      <div class="m-value">${m.totals.total}</div>
      <div class="m-sub">${m.totals.in} entrada · ${m.totals.out} salida</div>
    </div>`);

  if (peak) {
    cards.push(`
      <div class="metric-card">
        <div class="m-label">Hora de máxima demanda</div>
        <div class="m-value" style="font-size:1.5rem">${hhmm(peak.start)}–${hhmm(peak.end)}</div>
        <div class="m-sub">${peak.volume} vehículos en la hora</div>
      </div>`);

    if (peak.fhp !== null) {
      // El FHP se muestra siempre junto a su umbral: el número solo no
      // dice nada si no sabes contra qué compararlo.
      cards.push(`
        <div class="metric-card">
          <div class="m-label">Factor de hora pico (FHP)</div>
          <div class="m-value">${peak.fhp.toFixed(3)}</div>
          <div class="m-sub">
            ${peak.volume} ÷ (${peak.subperiodos} × ${peak.peak_interval_volume})
          </div>
          <span class="m-flag ${peak.flujo_irregular ? 'warn' : 'ok'}">
            ${peak.flujo_irregular ? 'Flujo irregular (&lt; 0.85)' : 'Flujo parejo (≥ 0.85)'}
          </span>
        </div>`);
    }
  } else {
    cards.push(`
      <div class="metric-card">
        <div class="m-label">Hora de máxima demanda</div>
        <div class="m-value" style="font-size:1.1rem; color:var(--text-muted)">—</div>
        <div class="m-sub">Se necesita al menos una hora completa de aforo para calcular la hora pico y el FHP.</div>
      </div>`);
  }

  const topType = Object.entries(m.composition_pct).sort((a, b) => b[1] - a[1])[0];
  if (topType) {
    const styleLabel = { car: 'automóviles', truck: 'camiones', bus: 'autobuses', motorcycle: 'motocicletas' }[topType[0]] || topType[0];
    cards.push(`
      <div class="metric-card">
        <div class="m-label">Composición dominante</div>
        <div class="m-value">${topType[1]}%</div>
        <div class="m-sub">${styleLabel}</div>
      </div>`);
  }

  return `<div class="metrics-row">${cards.join('')}</div>`;
}

// --- Reporte por carril -------------------------------------------------

function renderLaneReport(laneMetrics, intervalMinutes) {
  const section = document.createElement('div');
  section.className = 'lane-report';
  const intervals = laneMetrics.intervals;

  if (!intervals.length) {
    section.innerHTML = `<h3>${laneMetrics.lane_name}</h3><div class="empty-state">Sin cruces registrados en este carril todavía.</div>`;
    return section;
  }

  const peakStart = laneMetrics.peak_hour ? laneMetrics.peak_hour.peak_interval_start : null;
  const maxTotal = Math.max(...intervals.map(i => i.total));

  const rows = intervals.map(iv => {
    const isPeak = peakStart ? iv.start === peakStart : (iv.total === maxTotal && maxTotal > 0);
    return `
      <tr class="${isPeak ? 'peak' : ''}">
        <td>${formatIntervalLabel(iv.start, iv.end)}${isPeak ? '<span class="peak-badge">pico</span>' : ''}</td>
        <td class="num">${iv.in}</td>
        <td class="num">${iv.out}</td>
        <td class="num">${iv.total}</td>
      </tr>`;
  }).join('');

  const laneTotal = laneMetrics.total;

  section.innerHTML = `
    <h3>${laneMetrics.lane_name}</h3>
    <div class="summary-row">
      <span class="pill">Total <span class="value">${laneTotal}</span></span>
      <span class="pill">Entrada <span class="value">${laneMetrics.in}</span></span>
      <span class="pill">Salida <span class="value">${laneMetrics.out}</span></span>
      <span class="pill">${intervals.length} × ${intervalMinutes} min</span>
      ${laneMetrics.peak_hour && laneMetrics.peak_hour.fhp !== null
        ? `<span class="pill">FHP <span class="value">${laneMetrics.peak_hour.fhp.toFixed(3)}</span></span>` : ''}
    </div>

    <div class="chart-card">
      <h4>Volumen por intervalo</h4>
      <div class="chart-sub">Cada barra es un periodo de ${intervalMinutes} minutos. La barra ámbar es el intervalo de mayor demanda.</div>
      ${renderIntervalChart(intervals, { peakIntervalStart: peakStart })}
    </div>

    ${laneTotal > 0 ? `
      <div class="chart-card">
        <h4>Composición vehicular</h4>
        <div class="chart-sub">Proporción por tipo sobre el total del carril.</div>
        ${renderCompositionChart(laneMetrics.composition, laneTotal)}
      </div>` : ''}

    <details class="table-details">
      <summary>Ver tabla de cifras exactas</summary>
      <div class="table-scroll">
        <table class="interval-table">
          <thead>
            <tr><th>Intervalo</th><th>Entrada</th><th>Salida</th><th>Total</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </details>
  `;
  return section;
}

async function loadReport() {
  const projectId = projectSelect.value;
  const minutes = intervalSelect.value;

  if (!projectId) {
    reportBody.innerHTML = '<div class="empty-state">Selecciona una intersección para ver su reporte.</div>';
    return;
  }

  reportBody.innerHTML = '<div class="empty-state">Calculando…</div>';

  try {
    const res = await fetch(`/api/videos/metrics?project_id=${projectId}&minutes=${minutes}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const m = await res.json();

    if (!m.lanes.length) {
      reportBody.innerHTML = '<div class="empty-state">Esta intersección todavía no tiene carriles calibrados.</div>';
      return;
    }

    reportBody.innerHTML = renderMetrics(m);

    m.lanes.forEach(lane => {
      const section = renderLaneReport(lane, m.interval_minutes);
      reportBody.appendChild(section);
    });

    if (!REDUCED_MOTION && typeof gsap !== 'undefined') {
      gsap.from('.metric-card', { opacity: 0, y: 12, duration: 0.4, stagger: 0.05, ease: 'power3.out' });
      gsap.from('.chart-bar', {
        scaleY: 0, transformOrigin: 'bottom', duration: 0.5, stagger: 0.015, ease: 'power2.out'
      });
    }
  } catch (e) {
    reportBody.innerHTML = `<div class="empty-state">No se pudo cargar el reporte: ${e.message}</div>`;
  }
}

intervalSelect.addEventListener('change', loadReport);
loadProjectsInto(projectSelect, { onChange: loadReport, autoSelectFirst: true });
