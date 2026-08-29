/*
  Calibración de carriles: carga un frame real de la fuente elegida,
  el usuario hace clic en 2 puntos para dibujar la línea de conteo
  exactamente donde cruzan los vehículos, y se guarda con nombre.

  La flecha de "Entrada" se calcula con la MISMA fórmula (producto
  cruzado) que usa el backend en counter.py, para que no haya
  sorpresas entre lo que se ve aquí y lo que realmente cuenta el motor.
*/

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const LANE_COLORS = ['#ff5470', '#2dd4ff', '#ffd23f', '#7cff6b', '#c77dff', '#ff9f45'];

const projectSelect = document.getElementById("project-select");
const canvas = document.getElementById('calib-canvas');
const ctx = canvas.getContext('2d');
const hint = document.getElementById('calib-hint');
const laneList = document.getElementById('lane-list');
const newLaneBtn = document.getElementById('new-lane-btn');
const newLaneForm = document.getElementById('new-lane-form');
const newLaneNameInput = document.getElementById('new-lane-name');

let currentImage = null;
let lanes = [];
let drawMode = false;
let tempPoints = [];

function laneColor(index) { return LANE_COLORS[index % LANE_COLORS.length]; }

// Vector unitario hacia el lado que el backend clasifica como "Entrada"
// (mismo cálculo que _calculate_crossing_direction en counter.py).
function entradaDirection(p1, p2) {
  const lx = p2[0] - p1[0], ly = p2[1] - p1[1];
  const len = Math.hypot(lx, ly) || 1;
  const perp = [-ly / len, lx / len];
  const cross = perp[0] * ly - perp[1] * lx;
  return cross > 0 ? perp : [-perp[0], -perp[1]];
}

async function loadFrame(projectId) {
  hint.textContent = 'Cargando frame…';
  try {
    const res = await fetch(`/api/camera/snapshot?project_id=${projectId}`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      img.src = url;
    });
    currentImage = img;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    newLaneBtn.disabled = false;
    hint.textContent = 'Clic en "+ Nuevo carril" y marca 2 puntos donde cruzan los vehículos.';
    redraw();
    loadHeatmap(projectId).then(redraw);
  } catch (e) {
    currentImage = null;
    newLaneBtn.disabled = true;
    hint.textContent = `No se pudo cargar el frame: ${e.message}`;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}

async function loadLanes(projectId) {
  const res = await fetch(`/api/lanes?project_id=${projectId}`);
  lanes = res.ok ? await res.json() : [];
  renderLaneList();
  redraw();
  refreshStartCounting(projectId);
}

// --- Empezar conteo ----------------------------------------------------
// El botón solo aparece cuando de verdad hay algo que arrancar: carriles
// definidos Y videos esperando. Así el usuario no puede lanzar un conteo
// sobre una línea que no existe.

const startBox = document.getElementById('start-counting-box');
const startInfo = document.getElementById('sc-info');

async function refreshStartCounting(projectId) {
  if (!projectId) { startBox.classList.add('hidden'); return; }
  try {
    const res = await fetch(`/api/videos?project_id=${projectId}`);
    const jobs = res.ok ? await res.json() : [];
    const waiting = jobs.filter(j => j.status === 'awaiting_calibration');

    if (!waiting.length || !lanes.length) {
      startBox.classList.add('hidden');
      return;
    }
    startBox.classList.remove('hidden');
    startInfo.textContent =
      `${waiting.length} video${waiting.length > 1 ? 's' : ''} esperando, ` +
      `${lanes.length} carril${lanes.length > 1 ? 'es' : ''} definido${lanes.length > 1 ? 's' : ''}.`;
  } catch (e) {
    startBox.classList.add('hidden');
  }
}

document.getElementById('start-counting-btn').addEventListener('click', async () => {
  const projectId = projectSelect.value;
  if (!projectId) return;

  const btn = document.getElementById('start-counting-btn');
  btn.disabled = true;
  btn.textContent = 'Iniciando…';
  try {
    const res = await fetch(`/api/projects/${projectId}/start-counting`, { method: 'POST' });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    hint.textContent = `Conteo iniciado sobre ${body.started} video(s). Puedes seguir el avance en "Subir videos".`;
    refreshStartCounting(projectId);
  } catch (e) {
    alert(`No se pudo empezar el conteo: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Empezar conteo';
  }
});

function renderLaneList() {
  laneList.innerHTML = '';
  if (!lanes.length) {
    laneList.innerHTML = '<div class="empty-state" style="padding:16px">Sin carriles todavía.</div>';
  }
  lanes.forEach((lane, i) => {
    const row = document.createElement('div');
    row.className = 'lane-item';
    row.innerHTML = `
      <span class="lane-swatch" style="background:${laneColor(i)}"></span>
      <input type="text" class="lane-name-input" value="${lane.name}">
      <button type="button" class="lane-remove" aria-label="Eliminar carril">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    `;
    const nameInput = row.querySelector('.lane-name-input');
    nameInput.addEventListener('change', async () => {
      await fetch(`/api/lanes/${lane.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: nameInput.value })
      });
      lane.name = nameInput.value;
      redraw();
    });
    row.querySelector('.lane-remove').addEventListener('click', async () => {
      if (!confirm(`¿Eliminar el carril "${lane.name}"? Se conserva el historial de conteos ya registrado.`)) return;
      await fetch(`/api/lanes/${lane.id}`, { method: 'DELETE' });
      loadLanes(projectSelect.value);
    });
    laneList.appendChild(row);
  });
}

function drawArrow(from, dir, color) {
  const len = 26;
  const to = [from[0] + dir[0] * len, from[1] + dir[1] * len];
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(from[0], from[1]);
  ctx.lineTo(to[0], to[1]);
  ctx.stroke();
  const angle = Math.atan2(dir[1], dir[0]);
  ctx.beginPath();
  ctx.moveTo(to[0], to[1]);
  ctx.lineTo(to[0] - 8 * Math.cos(angle - 0.4), to[1] - 8 * Math.sin(angle - 0.4));
  ctx.lineTo(to[0] - 8 * Math.cos(angle + 0.4), to[1] - 8 * Math.sin(angle + 0.4));
  ctx.closePath();
  ctx.fill();
}

function drawLine(p1, p2, color, label) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(p1[0], p1[1]);
  ctx.lineTo(p2[0], p2[1]);
  ctx.stroke();

  [p1, p2].forEach(p => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(p[0], p[1], 5, 0, Math.PI * 2);
    ctx.fill();
  });

  const mid = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
  const dir = entradaDirection(p1, p2);
  drawArrow(mid, dir, color);

  if (label) {
    ctx.font = 'bold 14px sans-serif';
    ctx.fillStyle = '#000000cc';
    ctx.fillRect(mid[0] + 6, mid[1] - 18, ctx.measureText(label).width + 10, 20);
    ctx.fillStyle = color;
    ctx.fillText(label, mid[0] + 11, mid[1] - 3);
  }
}

function redraw() {
  if (!currentImage) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(currentImage, 0, 0, canvas.width, canvas.height);

  // El rastro de movimiento va encima del frame y debajo de las líneas, para
  // poder juzgar si la línea cruza el tránsito o corre a lo largo de él.
  if (showHeatmap && heatImage) {
    ctx.globalAlpha = 0.55;
    ctx.drawImage(heatImage, 0, 0, canvas.width, canvas.height);
    ctx.globalAlpha = 1;
  }

  lanes.forEach((lane, i) => drawLine(lane.points[0], lane.points[1], laneColor(i), lane.name));

  if (tempPoints.length === 1) {
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(tempPoints[0][0], tempPoints[0][1], 5, 0, Math.PI * 2);
    ctx.fill();
  } else if (tempPoints.length === 2) {
    drawLine(tempPoints[0], tempPoints[1], '#ffffff', null);
  }
}

canvas.addEventListener('click', e => {
  if (!drawMode || !currentImage) return;
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const point = [(e.clientX - rect.left) * scaleX, (e.clientY - rect.top) * scaleY];

  tempPoints.push(point);
  redraw();

  if (tempPoints.length === 2) {
    drawMode = false;
    validarLinea(tempPoints[0], tempPoints[1]);
    newLaneForm.classList.remove('hidden');
    newLaneNameInput.value = `Carril ${lanes.length + 1}`;
    newLaneNameInput.focus();
    newLaneNameInput.select();
    if (!REDUCED_MOTION && typeof gsap !== 'undefined') {
      gsap.from(newLaneForm, { opacity: 0, y: -6, duration: 0.25, ease: 'power2.out' });
    }
  }
});

newLaneBtn.addEventListener('click', () => {
  drawMode = true;
  tempPoints = [];
  newLaneForm.classList.add('hidden');
  hint.textContent = 'Marca el primer punto de la línea…';
  redraw();
});

document.getElementById('save-lane-btn').addEventListener('click', async () => {
  const name = newLaneNameInput.value.trim();
  if (!name || tempPoints.length !== 2) return;

  await fetch('/api/lanes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: parseInt(projectSelect.value, 10),
      name,
      points: tempPoints
    })
  });

  tempPoints = [];
  newLaneForm.classList.add('hidden');
  hint.textContent = 'Carril guardado. Puedes agregar otro o editar los existentes en la lista.';
  loadLanes(projectSelect.value);
});

function onProjectChange() {
  tempPoints = [];
  drawMode = false;
  newLaneForm.classList.add('hidden');
  const projectId = projectSelect.value;
  if (!projectId) {
    currentImage = null;
    newLaneBtn.disabled = true;
    lanes = [];
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    startBox.classList.add('hidden');
    hint.textContent = 'Elige una intersección arriba para cargar un frame.';
    return;
  }
  loadFrame(projectId);
  loadLanes(projectId);
}

loadProjectsInto(projectSelect, { onChange: onProjectChange, autoSelectFirst: true });

// --- Rastro de movimiento y validación de la línea ------------------------

const heatToggle = document.getElementById('heat-toggle');
const calibWarn = document.getElementById('calib-warn');

let heatImage = null;
let showHeatmap = false;

async function loadHeatmap(projectId) {
  heatImage = null;
  heatToggle.disabled = true;
  heatToggle.checked = false;
  showHeatmap = false;
  try {
    const res = await fetch(`/api/camera/heatmap?project_id=${projectId}`);
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    const img = new Image();
    await new Promise((ok, err) => { img.onload = ok; img.onerror = err; img.src = url; });
    heatImage = img;
    heatToggle.disabled = false;
  } catch (e) { /* sin rastro, la calibración sigue siendo posible a mano */ }
}

heatToggle.addEventListener('change', () => {
  showHeatmap = heatToggle.checked;
  redraw();
});

/**
 * Revisa que la línea recién dibujada sirva para contar y avisa si no.
 *
 * Los dos errores que de verdad arruinan un aforo:
 *  - Línea demasiado corta: los vehículos pasan por los lados sin tocarla.
 *  - Línea paralela al tránsito: el vehículo avanza A LO LARGO de ella en
 *    vez de cruzarla, así que casi nunca dispara un conteo.
 * Se avisa pero no se bloquea: puede haber escenas donde el usuario sepa
 * algo que este chequeo no.
 */
function validarLinea(p1, p2) {
  const problemas = [];
  const largo = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
  const pctAncho = (largo / canvas.width) * 100;

  if (pctAncho < 15) {
    problemas.push(
      `La línea mide solo ${Math.round(pctAncho)}% del ancho de la imagen. ` +
      `Si no cubre el carril completo, los vehículos pasan por los lados sin contarse.`
    );
  }

  if (heatImage) {
    const angulo = Math.abs(Math.atan2(p2[1] - p1[1], p2[0] - p1[0]) * 180 / Math.PI) % 180;
    const casiHorizontal = angulo < 25 || angulo > 155;
    if (casiHorizontal) {
      problemas.push(
        'La línea quedó casi horizontal. Si el tránsito también circula en ' +
        'horizontal, los vehículos avanzan a lo largo de ella y no la cruzan. ' +
        'Activa "Ver por dónde pasan los vehículos" y dibújala atravesando ese rastro.'
      );
    }
  }

  if (!problemas.length) {
    calibWarn.classList.add('hidden');
    calibWarn.innerHTML = '';
    return;
  }
  calibWarn.classList.remove('hidden');
  calibWarn.innerHTML = problemas.map(p => `⚠ ${p}`).join('<br><br>');
}
