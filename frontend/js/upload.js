/*
  Subida de videos (drag-and-drop o selector) + cola de procesamiento.
  Igual que el dashboard, actualiza el DOM en el lugar en vez de
  recrearlo en cada sondeo, para que la barra de progreso y las
  animaciones no salten.
*/

const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const POLL_MS = 3000;

const ALLOWED_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg'];

const STATUS_LABEL = {
  awaiting_calibration: 'falta calibrar',
  queued: 'en cola',
  processing: 'procesando',
  done: 'listo',
  error: 'error',
};

function fileExtension(filename) {
  const idx = filename.lastIndexOf('.');
  return idx === -1 ? '' : filename.slice(idx).toLowerCase();
}

function formatSize(bytes) {
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0, v = bytes;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

// --- Zona de arrastrar y soltar -----------------------------------------

const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const browseBtn = document.getElementById('browse-btn');
const rejectList = document.getElementById('reject-list');

function pulseDropzone(active) {
  if (REDUCED_MOTION || typeof gsap === 'undefined') return;
  gsap.to(dropzone, { scale: active ? 1.01 : 1, duration: 0.2, ease: 'power2.out' });
}

['dragenter', 'dragover'].forEach(evt => {
  dropzone.addEventListener(evt, e => {
    e.preventDefault();
    dropzone.classList.add('dragover');
    pulseDropzone(true);
  });
});
['dragleave', 'drop'].forEach(evt => {
  dropzone.addEventListener(evt, e => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    pulseDropzone(false);
  });
});
dropzone.addEventListener('drop', e => {
  const files = Array.from(e.dataTransfer.files || []);
  if (files.length) handleFiles(files);
});
dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
});
browseBtn.addEventListener('click', e => { e.stopPropagation(); fileInput.click(); });
fileInput.addEventListener('change', () => {
  if (fileInput.files.length) handleFiles(Array.from(fileInput.files));
  fileInput.value = '';
});

function showRejections(items) {
  items.forEach(item => {
    const el = document.createElement('div');
    el.className = 'reject-item';
    el.innerHTML = `<span class="rj-name">${item.filename}:</span> ${item.reason}`;
    rejectList.appendChild(el);
    if (!REDUCED_MOTION && typeof gsap !== 'undefined') {
      gsap.from(el, { opacity: 0, x: -8, duration: 0.3, ease: 'power2.out' });
    }
  });
}

// --- Panel de configuración previo a subir -------------------------------
// Los archivos no se suben al soltarlos: primero se arma la cola local
// (pendingFiles) con fuente/sesión, intervalo y hora real de inicio por
// archivo (adivinada del nombre cuando sigue el patrón HH-MM-SS), y solo
// se sube todo junto al confirmar — así el reporte por intervalos sale
// correcto desde el primer momento, no como un ajuste posterior.

const staging = document.getElementById('staging');
const stagingFiles = document.getElementById('staging-files');
const projectSelect = document.getElementById('project-select');
projectSelect.addEventListener('change', () => projectSelect.classList.remove('field-error'));
loadProjectsInto(projectSelect, { autoSelectFirst: true });

let pendingFiles = []; // { id, file, date, time }

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Reconoce nombres tipo "08-00-08_2ta.mkv" (HH-MM-SS al inicio del
// archivo) — patrón común en exports de cámaras de tránsito.
function guessStartTime(filename) {
  const m = filename.match(/^(\d{2})[-:_.](\d{2})[-:_.](\d{2})/);
  if (!m) return null;
  const [, hh, mm, ss] = m;
  if (+hh > 23 || +mm > 59 || +ss > 59) return null;
  return `${hh}:${mm}:${ss}`;
}

function renderStagingFiles() {
  stagingFiles.innerHTML = '';
  pendingFiles.forEach(entry => {
    const row = document.createElement('div');
    row.className = 'staging-file-row';
    row.innerHTML = `
      <span class="sf-name" title="${entry.file.name}">${entry.file.name}</span>
      <span class="sf-meta">${fileExtension(entry.file.name).replace('.', '').toUpperCase()} · ${formatSize(entry.file.size)}</span>
      <div class="sf-start">
        <span>inicio real:</span>
        <input type="date" value="${entry.date}" data-field="date">
        <input type="time" step="1" value="${entry.time}" data-field="time">
      </div>
      <button type="button" class="sf-remove" aria-label="Quitar">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    `;
    row.querySelector('[data-field="date"]').addEventListener('input', e => { entry.date = e.target.value; });
    row.querySelector('[data-field="time"]').addEventListener('input', e => { entry.time = e.target.value; });
    row.querySelector('.sf-remove').addEventListener('click', () => {
      pendingFiles = pendingFiles.filter(p => p.id !== entry.id);
      if (!pendingFiles.length) hideStaging();
      else renderStagingFiles();
    });
    stagingFiles.appendChild(row);
  });
}

function showStaging() {
  staging.classList.remove('hidden');
  if (!REDUCED_MOTION && typeof gsap !== 'undefined') {
    gsap.from(staging, { opacity: 0, y: -10, duration: 0.35, ease: 'power2.out' });
  }
}
function hideStaging() {
  staging.classList.add('hidden');
  pendingFiles = [];
  stagingFiles.innerHTML = '';
}

document.getElementById('cancel-staging').addEventListener('click', hideStaging);
document.getElementById('confirm-upload').addEventListener('click', confirmUpload);

async function handleFiles(files) {
  const clientRejected = [];

  for (const file of files) {
    const ext = fileExtension(file.name);
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      clientRejected.push({
        filename: file.name,
        reason: `Formato '${ext || 'desconocido'}' no soportado.`
      });
      continue;
    }
    const guessed = guessStartTime(file.name);
    pendingFiles.push({
      id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2)}`,
      file,
      date: todayISO(),
      time: guessed || '',
    });
  }
  if (clientRejected.length) showRejections(clientRejected);
  if (!pendingFiles.length) return;

  renderStagingFiles();
  showStaging();
}

async function confirmUpload() {
  const projectId = projectSelect.value;
  if (!projectId) {
    projectSelect.focus();
    projectSelect.classList.add('field-error');
    return;
  }

  const formData = new FormData();
  const startTimes = {};
  pendingFiles.forEach(entry => {
    formData.append('files', entry.file);
    if (entry.date && entry.time) {
      startTimes[entry.file.name] = `${entry.date} ${entry.time}`;
    }
  });
  formData.append('project_id', projectId);
  formData.append('start_times', JSON.stringify(startTimes));

  const uploadedFiles = pendingFiles.map(p => p.file.name);
  const confirmBtn = document.getElementById('confirm-upload');
  confirmBtn.disabled = true;
  confirmBtn.textContent = 'Subiendo…';

  try {
    const res = await fetch('/api/videos/upload', { method: 'POST', body: formData });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.rejected && data.rejected.length) showRejections(data.rejected);
    hideStaging();
    refreshJobs();
  } catch (e) {
    showRejections(uploadedFiles.map(name => ({ filename: name, reason: `Falló la subida: ${e.message}` })));
  } finally {
    confirmBtn.disabled = false;
    confirmBtn.textContent = 'Subir videos';
  }
}

// --- Cola de videos ------------------------------------------------------

const rendered = new Map(); // job.id -> { el, statusEl, progressBar, metaEl, deleteBtn }

function jobRowSkeleton(job) {
  const row = document.createElement('div');
  row.className = 'job-row';
  row.innerHTML = `
    <span class="job-icon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
        <rect x="2.5" y="5" width="14" height="14" rx="2"/>
        <path d="M16.5 9.5l5-2.5v10l-5-2.5z"/>
      </svg>
    </span>
    <div class="job-info">
      <div class="job-name"></div>
      <div class="job-meta"></div>
    </div>
    <div class="job-progress"><div class="bar" style="width:0%"></div></div>
    <span class="pill job-status"><span class="dot"></span><span class="status-text"></span></span>
    <button class="job-view hidden" aria-label="Ver video procesado" title="Ver qué detectó la IA">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/>
        <circle cx="12" cy="12" r="3"/>
      </svg>
    </button>
    <button class="job-delete" aria-label="Eliminar video" title="Eliminar">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
      </svg>
    </button>
  `;
  const player = document.createElement('div');
  player.className = 'job-player hidden';
  return { row, player };
}

async function deleteJob(jobId) {
  try {
    const res = await fetch(`/api/videos/${jobId}`, { method: 'DELETE' });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    refreshJobs();
  } catch (e) {
    alert(`No se pudo eliminar: ${e.message}`);
  }
}

function renderJobs(jobs) {
  const list = document.getElementById('job-list');
  const seenIds = new Set(jobs.map(j => j.id));

  for (const [id, entry] of rendered) {
    if (!seenIds.has(id)) {
      entry.el.remove();
      entry.player.remove();
      rendered.delete(id);
    }
  }

  if (!jobs.length) {
    if (!rendered.size) {
      list.innerHTML = '<div class="empty-state">Todavía no has subido ningún video.</div>';
    }
    return;
  }
  const emptyState = list.querySelector('.empty-state');
  if (emptyState) emptyState.remove();

  jobs.forEach(job => {
    let entry = rendered.get(job.id);
    const isNew = !entry;

    if (isNew) {
      const { row, player } = jobRowSkeleton(job);
      list.prepend(player);
      list.prepend(row);
      entry = {
        el: row,
        player,
        nameEl: row.querySelector('.job-name'),
        metaEl: row.querySelector('.job-meta'),
        bar: row.querySelector('.job-progress .bar'),
        statusPill: row.querySelector('.job-status'),
        statusText: row.querySelector('.status-text'),
        viewBtn: row.querySelector('.job-view'),
        deleteBtn: row.querySelector('.job-delete'),
        videoLoaded: false,
      };
      entry.deleteBtn.addEventListener('click', () => {
        if (confirm(`¿Eliminar "${job.original_name}"?`)) deleteJob(job.id);
      });
      entry.viewBtn.addEventListener('click', () => {
        const opening = entry.player.classList.contains('hidden');
        entry.player.classList.toggle('hidden');
        if (opening && !entry.videoLoaded) {
          entry.player.innerHTML = `<video controls preload="metadata" src="/api/videos/${job.id}/video"></video>`;
          entry.videoLoaded = true;
        }
        if (!REDUCED_MOTION && typeof gsap !== 'undefined' && opening) {
          gsap.from(entry.player, { opacity: 0, y: -8, duration: 0.3, ease: 'power2.out' });
        }
      });
      rendered.set(job.id, entry);
      if (!REDUCED_MOTION && typeof gsap !== 'undefined') {
        gsap.from(row, { opacity: 0, y: -8, duration: 0.35, ease: 'power2.out' });
      }
    }

    entry.nameEl.textContent = job.original_name;
    entry.nameEl.title = job.original_name;
    const fmt = fileExtension(job.original_name).replace('.', '').toUpperCase();
    const startLabel = job.video_start_time ? job.video_start_time.slice(11, 19) : 'sin hora';
    entry.metaEl.textContent =
      `${fmt} · ${formatSize(job.size_bytes)} · ${job.source_label} · inicio ${startLabel}`;

    const pct = job.total_frames
      ? Math.min(100, Math.round((job.processed_frames / job.total_frames) * 100))
      : (job.status === 'done' ? 100 : 0);
    entry.bar.style.width = `${pct}%`;

    entry.statusPill.className = `pill job-status status-${job.status}`;
    entry.statusText.textContent = job.status === 'error' && job.error
      ? `error: ${job.error}`
      : (STATUS_LABEL[job.status] || job.status);

    entry.deleteBtn.disabled = job.status === 'processing';
    entry.viewBtn.classList.toggle('hidden', job.status !== 'done');
  });
}

async function refreshJobs() {
  try {
    const res = await fetch('/api/videos');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    renderJobs(await res.json());
  } catch (e) {
    // Sondeo silencioso: no interrumpir la subida por un error de red pasajero
  }
}

function entranceAnimation() {
  if (REDUCED_MOTION || typeof gsap === 'undefined') return;
  gsap.timeline()
    .from('.topbar', { opacity: 0, y: -8, duration: 0.4, ease: 'power2.out' })
    .from('.dropzone', { opacity: 0, y: 14, duration: 0.5, ease: 'power2.out' }, '-=0.15');
}

entranceAnimation();
refreshJobs();
setInterval(refreshJobs, POLL_MS);
