/*
  Proyectos de aforo: lista de intersecciones con su histórico acumulado,
  y formulario de creación con mapa.

  La búsqueda de direcciones va contra /api/geo (nuestro backend), no
  contra Nominatim directo: su política exige User-Agent propio, 1 req/s
  y cachear resultados, y eso solo se puede garantizar del lado servidor.
*/

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const grid = document.getElementById('project-grid');
const form = document.getElementById('project-form');
const nameInput = document.getElementById('project-name');
const descInput = document.getElementById('project-description');
const intervalSelect = document.getElementById('project-interval');
const searchInput = document.getElementById('map-search-input');
const mapStatus = document.getElementById('map-status');
const mapCoords = document.getElementById('map-coords');

let map = null;
let marker = null;
let selected = { latitude: null, longitude: null, address: null };

// --- Mapa -------------------------------------------------------------

function initMap() {
  if (map || typeof L === 'undefined') return;

  // Los iconos del marcador viven en vendor/leaflet/images/ — que es
  // exactamente donde Leaflet los busca por su cuenta (relativo a su CSS).
  // Sobreescribir las rutas a mano hace que Leaflet les anteponga otra vez
  // su propio 'images/' y termine pidiendo una ruta duplicada que da 404.
  map = L.map('map').setView([23.6345, -102.5528], 5); // México, vista general
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap',
  }).addTo(map);

  map.on('click', e => setLocation(e.latlng.lat, e.latlng.lng, true));
}

function setLocation(lat, lon, lookupAddress) {
  selected.latitude = lat;
  selected.longitude = lon;
  mapCoords.textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;

  if (!marker) {
    marker = L.marker([lat, lon], { draggable: true }).addTo(map);
    marker.on('dragend', () => {
      const p = marker.getLatLng();
      setLocation(p.lat, p.lng, true);
    });
  } else {
    marker.setLatLng([lat, lon]);
  }

  if (lookupAddress) {
    mapStatus.textContent = 'Buscando dirección…';
    fetch(`/api/geo/reverse?lat=${lat}&lon=${lon}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error('sin resultado')))
      .then(data => {
        selected.address = data.display_name;
        mapStatus.textContent = data.display_name || 'Ubicación fijada';
      })
      .catch(() => {
        selected.address = null;
        mapStatus.textContent = 'Ubicación fijada (sin dirección disponible)';
      });
  }
}

async function searchAddress() {
  const q = searchInput.value.trim();
  if (q.length < 3) return;

  mapStatus.textContent = 'Buscando…';
  try {
    const res = await fetch(`/api/geo/search?q=${encodeURIComponent(q)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const results = await res.json();
    if (!results.length) {
      mapStatus.textContent = 'No se encontró esa dirección. Prueba con otra o haz clic en el mapa.';
      return;
    }
    const first = results[0];
    selected.address = first.display_name;
    map.setView([first.latitude, first.longitude], 17);
    setLocation(first.latitude, first.longitude, false);
    mapStatus.textContent = first.display_name;
  } catch (e) {
    mapStatus.textContent = `No se pudo buscar: ${e.message}`;
  }
}

document.getElementById('map-search-btn').addEventListener('click', searchAddress);
searchInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); searchAddress(); }
});

// --- Formulario --------------------------------------------------------

document.getElementById('new-project-btn').addEventListener('click', () => {
  form.classList.remove('hidden');
  initMap();
  // Leaflet calcula mal el tamaño si el contenedor estaba oculto al crearse
  setTimeout(() => map && map.invalidateSize(), 50);
  nameInput.focus();
  if (!REDUCED_MOTION && typeof gsap !== 'undefined') {
    gsap.from(form, { opacity: 0, y: -10, duration: 0.35, ease: 'power2.out' });
  }
});

document.getElementById('cancel-project').addEventListener('click', () => {
  form.classList.add('hidden');
  nameInput.value = '';
  descInput.value = '';
});

document.getElementById('save-project').addEventListener('click', async () => {
  const name = nameInput.value.trim();
  if (!name) {
    nameInput.focus();
    nameInput.classList.add('field-error');
    return;
  }

  const btn = document.getElementById('save-project');
  btn.disabled = true;
  btn.textContent = 'Creando…';

  try {
    const res = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        description: descInput.value.trim() || null,
        latitude: selected.latitude,
        longitude: selected.longitude,
        address: selected.address,
        interval_minutes: parseInt(intervalSelect.value, 10),
      })
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    form.classList.add('hidden');
    nameInput.value = '';
    descInput.value = '';
    selected = { latitude: null, longitude: null, address: null };
    if (marker) { marker.remove(); marker = null; }
    loadProjects();
  } catch (e) {
    alert(`No se pudo crear el proyecto: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Crear intersección';
  }
});

nameInput.addEventListener('input', () => nameInput.classList.remove('field-error'));

// --- Lista ------------------------------------------------------------

const PIN_ICON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-6-7-11a7 7 0 1114 0c0 5-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>';

async function loadProjects() {
  try {
    const res = await fetch('/api/projects');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const projects = await res.json();

    if (!projects.length) {
      grid.innerHTML = '<div class="empty-state">Todavía no hay intersecciones. Crea la primera con el botón de arriba.</div>';
      return;
    }

    grid.innerHTML = projects.map(p => `
      <div class="project-card">
        <div class="pc-head">
          <span class="pc-name">${p.name}</span>
          ${p.awaiting_count ? `<span class="pc-badge">${p.awaiting_count} sin calibrar</span>` : ''}
        </div>
        ${p.address ? `<div class="pc-address">${PIN_ICON}<span>${p.address}</span></div>` : ''}
        <div class="pc-stats">
          <div class="pc-stat accent">
            <div class="pc-stat-label">Cruces</div>
            <div class="pc-stat-value">${p.crossing_count}</div>
          </div>
          <div class="pc-stat">
            <div class="pc-stat-label">Videos</div>
            <div class="pc-stat-value">${p.video_count}</div>
          </div>
          <div class="pc-stat">
            <div class="pc-stat-label">Carriles</div>
            <div class="pc-stat-value">${p.lane_count}</div>
          </div>
        </div>
        <div class="pc-actions">
          <a href="subir.html?project=${p.id}">Subir videos</a>
          <a href="calibrar.html?project=${p.id}">Calibrar</a>
          <a href="reporte.html?project=${p.id}">Reporte</a>
        </div>
      </div>
    `).join('');

    if (!REDUCED_MOTION && typeof gsap !== 'undefined') {
      gsap.from('.project-card', { opacity: 0, y: 14, duration: 0.45, stagger: 0.05, ease: 'power3.out' });
    }
  } catch (e) {
    grid.innerHTML = `<div class="empty-state">No se pudieron cargar los proyectos: ${e.message}</div>`;
  }
}

loadProjects();
