/*
  Gráficas en SVG puro — sin librería externa, para no cargar otro bundle
  en un equipo que ya está ocupado corriendo YOLO.

  Decisiones de diseño (ver skill data-visualization):
  - Barras para comparar intervalos, con el eje SIEMPRE en cero: en un
    aforo, truncar el eje exagera visualmente diferencias de tránsito.
  - Etiqueta directa sobre la barra en vez de leyenda cuando cabe.
  - La paleta por tipo de vehículo varía en tono Y luminosidad, para que
    siga siendo legible con daltonismo y en impresión a escala de grises.
  - Toda gráfica va acompañada de su tabla equivalente (la que ya existe),
    que es la alternativa accesible y además lo que un ingeniero necesita
    para copiar cifras exactas.
*/

const VEHICLE_COLORS = {
  car:        { fill: '#1d54b3', label: 'Automóvil' },
  truck:      { fill: '#c2751a', label: 'Camión' },
  bus:        { fill: '#7a3fb8', label: 'Autobús' },
  motorcycle: { fill: '#12868f', label: 'Motocicleta' },
};
const VEHICLE_FALLBACK = { fill: '#5d6a7d', label: 'Otro' };

function vehicleStyle(type) {
  return VEHICLE_COLORS[type] || { ...VEHICLE_FALLBACK, label: type };
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/**
 * Gráfica de barras de volumen por intervalo.
 * Resalta el intervalo pico y dibuja la línea del promedio como referencia.
 */
function renderIntervalChart(intervals, { peakIntervalStart = null } = {}) {
  if (!intervals.length) return '<div class="chart-empty">Sin datos para graficar</div>';

  const W = 720, H = 260;
  const PAD = { top: 24, right: 16, bottom: 46, left: 44 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const maxVal = Math.max(...intervals.map(i => i.total), 1);
  // Escala redondeada hacia arriba para que la cuadrícula caiga en números limpios
  const step = Math.max(1, Math.ceil(maxVal / 4));
  const yMax = step * 4;

  const barGap = 4;
  const barW = Math.max(3, (plotW / intervals.length) - barGap);
  const x = i => PAD.left + i * (plotW / intervals.length) + barGap / 2;
  const y = v => PAD.top + plotH - (v / yMax) * plotH;

  const avg = intervals.reduce((s, i) => s + i.total, 0) / intervals.length;

  // Cuadrícula + eje Y
  let grid = '';
  for (let t = 0; t <= 4; t++) {
    const val = step * t;
    const yy = y(val);
    grid += `<line class="chart-grid" x1="${PAD.left}" y1="${yy}" x2="${W - PAD.right}" y2="${yy}"/>`;
    grid += `<text class="chart-axis" x="${PAD.left - 8}" y="${yy + 4}" text-anchor="end">${val}</text>`;
  }

  // Barras. Se etiqueta el valor solo si la barra es lo bastante ancha para
  // que el número no se encime con el vecino.
  const showValues = barW >= 22;
  let bars = '';
  intervals.forEach((iv, i) => {
    const isPeak = peakIntervalStart && iv.start === peakIntervalStart;
    const h = Math.max(iv.total > 0 ? 2 : 0, (iv.total / yMax) * plotH);
    const yy = PAD.top + plotH - h;
    const label = iv.start.slice(11, 16);
    bars += `
      <g class="chart-bar-group">
        <rect class="chart-bar${isPeak ? ' is-peak' : ''}" x="${x(i)}" y="${yy}"
              width="${barW}" height="${h}" rx="3">
          <title>${esc(label)} — ${iv.total} vehículos (${iv.in} entrada / ${iv.out} salida)</title>
        </rect>
        ${showValues && iv.total > 0
          ? `<text class="chart-value" x="${x(i) + barW / 2}" y="${yy - 6}" text-anchor="middle">${iv.total}</text>`
          : ''}
        <text class="chart-axis" x="${x(i) + barW / 2}" y="${H - PAD.bottom + 18}"
              text-anchor="middle">${esc(label)}</text>
      </g>`;
  });

  // Referencia: promedio del periodo. Da contexto para leer si un
  // intervalo está por encima o por debajo de lo normal del aforo.
  const avgY = y(avg);
  const avgLine = `
    <line class="chart-avg" x1="${PAD.left}" y1="${avgY}" x2="${W - PAD.right}" y2="${avgY}"/>
    <text class="chart-avg-label" x="${W - PAD.right}" y="${avgY - 5}" text-anchor="end">promedio ${avg.toFixed(1)}</text>`;

  return `
    <svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
         aria-label="Volumen de vehículos por intervalo. Máximo ${maxVal}, promedio ${avg.toFixed(1)}.">
      ${grid}
      ${avgLine}
      ${bars}
      <text class="chart-axis-title" x="${PAD.left}" y="${H - 6}">Hora de inicio del intervalo</text>
    </svg>`;
}

/**
 * Composición vehicular como barra apilada horizontal.
 * Se eligió apilada y no dona porque el dato que importa es la proporción
 * relativa entre 2-4 categorías, y una barra permite leer los porcentajes
 * en línea sin tener que comparar ángulos.
 */
function renderCompositionChart(composition, total) {
  const entries = Object.entries(composition).filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length || !total) return '<div class="chart-empty">Sin vehículos clasificados</div>';

  let offset = 0;
  const segments = entries.map(([type, n]) => {
    const pct = (n / total) * 100;
    const style = vehicleStyle(type);
    const seg = `<div class="comp-seg" style="width:${pct}%; background:${style.fill}"
                      title="${esc(style.label)}: ${n} (${pct.toFixed(1)}%)"></div>`;
    offset += pct;
    return seg;
  }).join('');

  const legend = entries.map(([type, n]) => {
    const style = vehicleStyle(type);
    const pct = (n / total) * 100;
    return `<div class="comp-legend-item">
        <span class="comp-swatch" style="background:${style.fill}"></span>
        <span class="comp-label">${esc(style.label)}</span>
        <span class="comp-num">${n}</span>
        <span class="comp-pct">${pct.toFixed(1)}%</span>
      </div>`;
  }).join('');

  return `
    <div class="comp-bar" role="img" aria-label="Composición vehicular: ${
      entries.map(([t, n]) => `${vehicleStyle(t).label} ${((n / total) * 100).toFixed(1)}%`).join(', ')
    }">${segments}</div>
    <div class="comp-legend">${legend}</div>`;
}
